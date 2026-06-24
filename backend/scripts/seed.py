#!/usr/bin/env python
"""Standalone COPY-based analytics seeder (US3).

Bulk-inserts a large, **user-owned** completed-send dataset directly into the lifecycle tables —
bypassing the live send/resilience pipeline — so the per-UTC-hour aggregation (data-model §3.1) can
be exercised at scale (≈1,000 accounts, ≈500,000 sends across all 24 UTC hours and many dates).

Design notes:

- Uses PostgreSQL ``COPY ... FROM STDIN`` on the **sync (psycopg) engine** — the fast path for bulk
  load. No ORM, no idempotency keys, no circuit breaker, no Celery fan-out (FR-021–FR-023).
- Each "send" is one ``dispatch`` (real ``user_id``) + one ``delivery`` (``sent``/``delivered``) +
  one ``delivery_transition`` (``to_status='sent'`` with an **explicit** ``at``). Only that ``sent``
  transition feeds the aggregation, so the per-hour totals are deterministic.
- Generation is driven by a **reseeded** ``random.Random`` so each COPY pass reproduces the exact
  same rows; that keeps the foreign-key chain consistent across passes without buffering millions of
  tuples in memory (parents must be COPYed before their children — FKs are not deferrable).

Run it (defaults to the spec's ≈1,000 / ≈500,000):

    uv run python backend/scripts/seed.py --accounts 1000 --sends 500000
"""

from __future__ import annotations

import argparse
import random
import sys
import uuid
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple

from sqlalchemy import Engine

# A constant, non-secret stand-in (the seeded accounts exist only for aggregation volume and never
# log in). Avoids paying argon2 per row; data-model §7 explicitly permits a fixed hash.
_FIXED_PASSWORD_HASH = "seed-account-not-a-login"  # noqa: S105 — placeholder, not a credential
_CHANNELS = ("email", "sms", "push")  # never 'report' — those are server-owned, not user sends
_TITLE = "Seeded notification"
_CONTENT = "Seeded analytics dataset send."
_RECIPIENT = "Seed Recipient"
# Spread sends over a month of dates so distribution checks see many distinct days (SC-005/SC-007).
_NUM_DAYS = 30
_BASE = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
_DEFAULT_RNG_SEED = 1234

_DEFAULT_ACCOUNTS = 1_000
_DEFAULT_SENDS = 500_000


class _Send(NamedTuple):
    """One generated send across the dispatch/delivery/transition chain."""

    dispatch_id: uuid.UUID
    delivery_id: uuid.UUID
    user_id: uuid.UUID
    channel: str
    at: datetime
    at_date: date
    hour: int
    status: str
    destination: str


@dataclass
class SeedResult:
    """What the seeder generated — the tests assert the DB matches this."""

    accounts: int
    sends: int
    hour_counts: dict[int, int]  # UTC hour -> number of 'sent' transitions (data-model §3.1)
    dates: tuple[date, ...]


def _generate_sends(rng_seed: int, sends: int, user_ids: list[uuid.UUID]) -> Iterator[_Send]:
    """Reproducibly yield ``sends`` records. Reseeded on every call so each COPY pass regenerates
    the identical chain (stable dispatch/delivery ids keep the foreign keys consistent)."""
    rng = random.Random(rng_seed)
    n_users = len(user_ids)
    for i in range(sends):
        user_id = user_ids[rng.randrange(n_users)]
        channel = _CHANNELS[rng.randrange(len(_CHANNELS))]
        dispatch_id = uuid.UUID(int=rng.getrandbits(128), version=4)
        delivery_id = uuid.UUID(int=rng.getrandbits(128), version=4)
        hour = i % 24  # deterministic: guarantees all 24 UTC hours appear once sends >= 24
        at = (_BASE - timedelta(days=i % _NUM_DAYS)).replace(
            hour=hour, minute=i % 60, second=0, microsecond=0
        )
        # Both 'sent' and 'delivered' reached 'sent' (one 'sent' transition each) — data-model §7.
        status = "delivered" if i % 2 == 0 else "sent"
        destination = f"recipient-{i:06d}@seed.example.com"
        yield _Send(
            dispatch_id=dispatch_id,
            delivery_id=delivery_id,
            user_id=user_id,
            channel=channel,
            at=at,
            at_date=at.date(),
            hour=hour,
            status=status,
            destination=destination,
        )


def _copy_rows(conn: Any, sql: str, rows: Iterator[tuple[object, ...]]) -> None:
    with conn.cursor() as cur, cur.copy(sql) as copy:  # conn is the raw psycopg3 Connection
        for row in rows:
            copy.write_row(row)


def seed(
    engine: Engine, *, accounts: int, sends: int, rng_seed: int = _DEFAULT_RNG_SEED
) -> SeedResult:
    """Bulk-load ``accounts`` users and ``sends`` completed user-owned sends via COPY.

    Parents are COPYed before children inside a single transaction (immediate FKs), then committed.
    Returns the generated per-UTC-hour totals so callers/tests can verify the aggregation."""
    user_ids = [uuid.uuid4() for _ in range(accounts)]

    hour_counts: Counter[int] = Counter()
    dates: set[date] = set()

    def transition_rows() -> Iterator[tuple[object, ...]]:
        for s in _generate_sends(rng_seed, sends, user_ids):
            hour_counts[s.hour] += 1
            dates.add(s.at_date)
            yield (s.delivery_id, "queued", "sent", s.at)

    raw = engine.raw_connection()
    try:
        conn: Any = raw.driver_connection  # the underlying psycopg3 Connection
        _copy_rows(
            conn,
            "COPY user_account (id, email, password_hash, is_verified, is_admin) FROM STDIN",
            (
                (uid, f"seed-user-{i:06d}@seed.example.com", _FIXED_PASSWORD_HASH, True, False)
                for i, uid in enumerate(user_ids)
            ),
        )
        _copy_rows(
            conn,
            "COPY dispatch (id, user_id, channel, title, content) FROM STDIN",
            (
                (s.dispatch_id, s.user_id, s.channel, _TITLE, _CONTENT)
                for s in _generate_sends(rng_seed, sends, user_ids)
            ),
        )
        _copy_rows(
            conn,
            "COPY delivery (id, dispatch_id, recipient_name, destination, status) FROM STDIN",
            (
                (s.delivery_id, s.dispatch_id, _RECIPIENT, s.destination, s.status)
                for s in _generate_sends(rng_seed, sends, user_ids)
            ),
        )
        _copy_rows(
            conn,
            "COPY delivery_transition (delivery_id, from_status, to_status, at) FROM STDIN",
            transition_rows(),
        )
        conn.commit()
    finally:
        raw.close()

    return SeedResult(
        accounts=accounts,
        sends=sends,
        hour_counts=dict(hour_counts),
        dates=tuple(sorted(dates)),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bulk-seed the analytics dataset via COPY.")
    parser.add_argument("--accounts", type=int, default=_DEFAULT_ACCOUNTS)
    parser.add_argument("--sends", type=int, default=_DEFAULT_SENDS)
    parser.add_argument(
        "--seed",
        type=int,
        default=_DEFAULT_RNG_SEED,
        dest="rng_seed",
        help="RNG seed for reproducible data (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    # Make `app` importable when launched as a file (uv run python backend/scripts/seed.py).
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.infra.db.sync_engine import get_sync_engine

    result = seed(
        get_sync_engine(), accounts=args.accounts, sends=args.sends, rng_seed=args.rng_seed
    )
    print(
        f"Seeded {result.accounts} accounts and {result.sends} sends "
        f"across {len(result.hour_counts)} UTC hours and {len(result.dates)} dates."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
