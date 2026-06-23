"""US3 — seeded analytics dataset (T041).

Runs ``backend/scripts/seed.py`` at reduced N and asserts the dataset's shape and that the
per-UTC-hour aggregation (data-model §3.1, ``SyncReportAggregationRepository``) exactly matches the
generated counts (SC-005/SC-007). The seeder is a standalone script (not under ``app``), so it is
loaded by file path."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.integration

_SEED_PATH = Path(__file__).resolve().parents[2] / "scripts" / "seed.py"

_ACCOUNTS = 20
_SENDS = 2_000
_RNG_SEED = 7

# The §3.1-aggregation tables the seeder writes (children first for the start-of-test reset).
_SEED_TABLES = "delivery_transition, delivery, dispatch, user_account"


def _load_seed() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed", _SEED_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclasses can resolve the module's stringized annotations.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_seed_reduced_n_matches_aggregation(
    sync_session_factory: sessionmaker[Session],
    truncate_notification_tables: None,
) -> None:
    from app.adapters.persistence.sync_repo import SyncReportAggregationRepository
    from app.infra.db.sync_engine import get_sync_engine

    factory = sync_session_factory
    engine = get_sync_engine()

    # Clean slate (a prior test may have left rows that COPY would collide with / inflate counts).
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {_SEED_TABLES} RESTART IDENTITY CASCADE"))

    seed = _load_seed()
    result = seed.seed(engine, accounts=_ACCOUNTS, sends=_SENDS, rng_seed=_RNG_SEED)

    assert result.accounts == _ACCOUNTS
    assert result.sends == _SENDS

    # --- Counts + distribution land in the DB (SC-005/SC-007) ---
    with factory() as session:
        accounts = session.execute(text("SELECT count(*) FROM user_account")).scalar_one()
        sent = session.execute(
            text("SELECT count(*) FROM delivery_transition WHERE to_status = 'sent'")
        ).scalar_one()
        hours = session.execute(
            text(
                "SELECT count(DISTINCT EXTRACT(HOUR FROM at AT TIME ZONE 'UTC')) "
                "FROM delivery_transition WHERE to_status = 'sent'"
            )
        ).scalar_one()
        dates = session.execute(
            text(
                "SELECT count(DISTINCT (at AT TIME ZONE 'UTC')::date) "
                "FROM delivery_transition WHERE to_status = 'sent'"
            )
        ).scalar_one()

    assert accounts == _ACCOUNTS
    assert sent == _SENDS
    assert hours == 24  # every UTC hour is represented
    assert dates >= 2  # spread across multiple dates

    # --- The §3.1 aggregation per-hour totals exactly match what was generated --------------------
    agg = SyncReportAggregationRepository(factory)
    assert dict(agg.global_hour_counts()) == result.hour_counts

    # Per-user grid sums back to the same global per-hour totals (server-owned rows would be
    # excluded, but the seeder only writes user-owned sends).
    summed: dict[int, int] = {}
    for grid in agg.per_user_hour_counts().values():
        for hour, count in grid.items():
            summed[hour] = summed.get(hour, 0) + count
    assert summed == result.hour_counts
