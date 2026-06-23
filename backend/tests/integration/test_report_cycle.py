from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email import message_from_bytes

import pytest
from sqlalchemy import create_engine, text

from tests.conftest import SmtpSink
from tests.factories import make_admin, make_sent_delivery, make_user

pytestmark = pytest.mark.integration

_ADMIN = "admin@example.com"
_ALICE = "alice@example.com"
_BOB = "bob@example.com"


def _nudge_due(sync_url: str) -> None:
    """Make the config due now: interval 24h, anchor 2 days ago."""
    from app.adapters.persistence.sync_repo import SyncStatsConfigRepository
    from app.infra.db.sync_engine import get_sync_sessionmaker

    SyncStatsConfigRepository(get_sync_sessionmaker()).set_interval(
        86_400, datetime.now(UTC) - timedelta(days=2)
    )


def _report_rows(sync_url: str) -> list[tuple[str | None, str]]:
    """(destination, status) for every server-owned report delivery."""
    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT dl.destination, dl.status FROM delivery dl "
                    "JOIN dispatch d ON d.id = dl.dispatch_id "
                    "WHERE d.channel = 'report' AND d.user_id IS NULL"
                )
            ).all()
        return [(row[0], row[1]) for row in rows]
    finally:
        engine.dispose()


def _wait_for_reports(
    sync_url: str, *, count: int, timeout: float = 60.0
) -> list[tuple[str | None, str]]:
    deadline = time.time() + timeout
    rows: list[tuple[str | None, str]] = []
    while time.time() < deadline:
        rows = _report_rows(sync_url)
        if len(rows) >= count and all(status == "sent" for _, status in rows):
            return rows
        time.sleep(0.5)
    return rows


def test_report_cycle_end_to_end(
    report_workers: Callable[[], None],
    smtp_sink: SmtpSink,
    migrated_db: tuple[str, str, str],
) -> None:
    sync_url = migrated_db[1]
    from app.adapters.persistence.sync_repo import SyncReportAggregationRepository
    from app.infra.db.sync_engine import get_sync_sessionmaker

    factory = get_sync_sessionmaker()
    admin = make_admin(factory, email=_ADMIN)
    alice = make_user(factory, email=_ALICE)
    make_user(factory, email=_BOB)  # zero-send user → all-zero graph, still reported

    make_sent_delivery(factory, user_id=alice.id, at=datetime(2026, 6, 1, 9, 0, tzinfo=UTC))
    make_sent_delivery(factory, user_id=alice.id, at=datetime(2026, 6, 2, 9, 30, tzinfo=UTC))
    make_sent_delivery(factory, user_id=alice.id, at=datetime(2026, 6, 1, 14, 0, tzinfo=UTC))
    make_sent_delivery(factory, user_id=admin.id, at=datetime(2026, 6, 1, 3, 0, tzinfo=UTC))

    # --- Aggregation correctness (per-scope 24-bucket vs seeded; never-sent excluded) -------------
    agg = SyncReportAggregationRepository(factory)
    per_user = agg.per_user_hour_counts()
    assert dict(per_user[alice.id]) == {9: 2, 14: 1}
    assert dict(per_user[admin.id]) == {3: 1}
    assert alice.id in per_user and admin.id in per_user  # bob (zero) absent from the grid

    global_counts = dict(agg.global_hour_counts())
    assert global_counts == {
        3: 1,
        9: 2,
        14: 1,
    }  # = sum across users, admin included, no double-count

    # --- Drive one real cycle (cpu aggregate+render → io deliver → aiosmtpd sink) -----------------
    _nudge_due(sync_url)
    report_workers()

    rows = _wait_for_reports(sync_url, count=4)
    assert len(rows) == 4, rows  # alice + bob + admin(personal) + admin(global)
    assert all(status == "sent" for _, status in rows)  # each report rests at 'sent' (FR-019)

    destinations = sorted(dest for dest, _ in rows if dest is not None)
    assert destinations == sorted([_ALICE, _BOB, _ADMIN, _ADMIN])  # admin gets exactly two (SC-004)

    # The report emails actually reached SMTP, carrying a PNG attachment.
    deadline = time.time() + 30.0
    while len(smtp_sink.messages) < 4 and time.time() < deadline:
        time.sleep(0.3)
    assert len(smtp_sink.messages) == 4
    parsed = message_from_bytes(smtp_sink.messages[0])
    assert any(part.get_content_type() == "image/png" for part in parsed.walk())

    # --- Server-owned reports are excluded from every user's send-history (FR-019/FR-020) ---------
    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            for uid in (admin.id, alice.id):
                owned_report = conn.execute(
                    text(
                        "SELECT count(*) FROM dispatch WHERE user_id = :uid AND channel = 'report'"
                    ),
                    {"uid": uid},
                ).scalar_one()
                assert owned_report == 0
    finally:
        engine.dispose()

    # --- A second cycle leaves the histograms identical (no recursion, SC-009) --------------------
    _nudge_due(sync_url)
    report_workers()
    _wait_for_reports(sync_url, count=8)

    per_user_again = SyncReportAggregationRepository(factory).per_user_hour_counts()
    assert dict(per_user_again[alice.id]) == {9: 2, 14: 1}
    assert dict(per_user_again[admin.id]) == {3: 1}
    assert dict(SyncReportAggregationRepository(factory).global_hour_counts()) == {
        3: 1,
        9: 2,
        14: 1,
    }
