from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.persistence import models
from app.adapters.persistence.models import LivenessCompletion
from app.domain.channels import Channel
from app.domain.dispatch import Delivery, DeliveryStatus, Dispatch
from app.domain.stats import DEFAULT_INTERVAL_SECONDS, StatsReportConfig
from app.ports.repositories import AccountRef


class SyncLivenessCompletionWriter:
    """Implements LivenessCompletionWriter using the synchronous (psycopg) engine."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def record(self, correlation_id: UUID, pool_label: str) -> None:
        with self._session_factory() as session:
            session.add(LivenessCompletion(correlation_id=correlation_id, pool_label=pool_label))
            session.commit()


def _to_dispatch(row: models.Dispatch) -> Dispatch:
    return Dispatch(
        id=row.id,
        user_id=row.user_id,
        channel=Channel(row.channel),
        title=row.title,
        content=row.content,
        created_at=row.created_at,
        attachment=row.attachment_png,
    )


def _to_delivery(row: models.Delivery) -> Delivery:
    return Delivery(
        id=row.id,
        dispatch_id=row.dispatch_id,
        recipient_name=row.recipient_name,
        status=DeliveryStatus(row.status),
        destination=row.destination,
        failure_reason=row.failure_reason,
        provider_ref=row.provider_ref,
        contact_id=row.contact_id,
    )


class SyncDispatchReader:
    """Implements SyncDispatchReader using the synchronous (psycopg) engine."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, dispatch_id: UUID) -> Dispatch | None:
        with self._session_factory() as session:
            row = session.get(models.Dispatch, dispatch_id)
            return _to_dispatch(row) if row is not None else None


class SyncDeliveryRepository:
    """Implements SyncDeliveryRepository using the synchronous (psycopg) engine; the worker writes
    deliveries + append-only transitions here (NEVER the async engine — constitution III)."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, delivery_id: UUID) -> Delivery | None:
        with self._session_factory() as session:
            row = session.get(models.Delivery, delivery_id)
            return _to_delivery(row) if row is not None else None

    def queued_ids_for_dispatch(self, dispatch_id: UUID) -> list[UUID]:
        with self._session_factory() as session:
            result = session.execute(
                select(models.Delivery.id).where(
                    models.Delivery.dispatch_id == dispatch_id,
                    models.Delivery.status == DeliveryStatus.QUEUED.value,
                )
            )
            return list(result.scalars().all())

    def record_sent(self, delivery_id: UUID, *, provider_ref: str, attempt: int | None) -> None:
        with self._session_factory() as session:
            row = session.get(models.Delivery, delivery_id)
            if row is None:
                return
            from_status = row.status
            row.status = DeliveryStatus.SENT.value
            row.provider_ref = provider_ref
            session.add(
                models.DeliveryTransition(
                    delivery_id=delivery_id,
                    from_status=from_status,
                    to_status=DeliveryStatus.SENT.value,
                    attempt=attempt,
                )
            )
            session.commit()

    def record_failed(self, delivery_id: UUID, *, reason: str, attempt: int | None) -> None:
        with self._session_factory() as session:
            row = session.get(models.Delivery, delivery_id)
            if row is None:
                return
            from_status = row.status
            row.status = DeliveryStatus.FAILED.value
            row.failure_reason = reason
            session.add(
                models.DeliveryTransition(
                    delivery_id=delivery_id,
                    from_status=from_status,
                    to_status=DeliveryStatus.FAILED.value,
                    reason=reason,
                    attempt=attempt,
                )
            )
            session.commit()

    def confirm(self, delivery_id: UUID, *, outcome: DeliveryStatus, reason: str | None) -> bool:
        with self._session_factory() as session:
            row = session.get(models.Delivery, delivery_id)
            if row is None or row.status != DeliveryStatus.SENT.value:
                return False
            row.status = outcome.value
            if outcome is DeliveryStatus.FAILED:
                row.failure_reason = reason
            session.add(
                models.DeliveryTransition(
                    delivery_id=delivery_id,
                    from_status=DeliveryStatus.SENT.value,
                    to_status=outcome.value,
                    reason=reason,
                )
            )
            session.commit()
            return True


class SyncIdempotencyKeyRepository:
    """Implements IdempotencyKeyRepository using the synchronous (psycopg) engine. A unique
    violation on insert means a prior attempt already claimed (and delivered) this delivery."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def claim(self, delivery_id: UUID, key: str) -> bool:
        with self._session_factory() as session:
            session.add(models.IdempotencyKey(delivery_id=delivery_id, key=key))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                return False
            return True


# --- 004 stats-report (sync engine: Beat tick / cycle) -------------------------------------------


def _to_stats_config(row: models.StatsReportConfig) -> StatsReportConfig:
    return StatsReportConfig(interval_seconds=row.interval_seconds, anchor_at=row.anchor_at)


class SyncStatsConfigRepository:
    """Sync impl of the stats-report config singleton (mirrors AsyncStatsConfigRepository)."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self) -> StatsReportConfig:
        with self._session_factory() as session:
            row = session.get(models.StatsReportConfig, 1)
            if row is None:
                row = models.StatsReportConfig(id=1, interval_seconds=DEFAULT_INTERVAL_SECONDS)
                session.add(row)
                session.commit()
                session.refresh(row)
            return _to_stats_config(row)

    def set_interval(self, seconds: int, anchor_at: datetime) -> None:
        with self._session_factory() as session:
            row = session.get(models.StatsReportConfig, 1)
            if row is None:
                session.add(
                    models.StatsReportConfig(id=1, interval_seconds=seconds, anchor_at=anchor_at)
                )
            else:
                row.interval_seconds = seconds
                row.anchor_at = anchor_at
            session.commit()

    def advance_anchor(self, anchor_at: datetime) -> None:
        with self._session_factory() as session:
            row = session.get(models.StatsReportConfig, 1)
            if row is not None:
                row.anchor_at = anchor_at
                session.commit()


# "Reached at least 'sent'" = a delivery_transition row to_status='sent' (written once by
# record_sent). Filtered user_id IS NOT NULL so server-owned reports never count.
_PER_USER_HOUR_SQL = text(
    "SELECT d.user_id AS user_id, "
    "EXTRACT(HOUR FROM dt.at AT TIME ZONE 'UTC')::int AS hour, COUNT(*) AS sends "
    "FROM delivery_transition dt "
    "JOIN delivery dl ON dl.id = dt.delivery_id "
    "JOIN dispatch d ON d.id = dl.dispatch_id "
    "WHERE dt.to_status = 'sent' AND d.user_id IS NOT NULL "
    "GROUP BY d.user_id, hour"
)

_GLOBAL_HOUR_SQL = text(
    "SELECT EXTRACT(HOUR FROM dt.at AT TIME ZONE 'UTC')::int AS hour, COUNT(*) AS sends "
    "FROM delivery_transition dt "
    "JOIN delivery dl ON dl.id = dt.delivery_id "
    "JOIN dispatch d ON d.id = dl.dispatch_id "
    "WHERE dt.to_status = 'sent' AND d.user_id IS NOT NULL "
    "GROUP BY hour"
)


class SyncReportAggregationRepository:
    """Reads the per-UTC-hour send aggregate from the existing lifecycle tables (data-model §3)."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def per_user_hour_counts(self) -> Mapping[UUID, Mapping[int, int]]:
        grid: dict[UUID, dict[int, int]] = defaultdict(dict)
        with self._session_factory() as session:
            for user_id, hour, sends in session.execute(_PER_USER_HOUR_SQL):
                grid[user_id][hour] = sends
        return grid

    def global_hour_counts(self) -> Mapping[int, int]:
        counts: dict[int, int] = {}
        with self._session_factory() as session:
            for hour, sends in session.execute(_GLOBAL_HOUR_SQL):
                counts[hour] = sends
        return counts

    def list_accounts(self) -> Sequence[AccountRef]:
        with self._session_factory() as session:
            rows = session.execute(
                select(
                    models.UserAccount.id,
                    models.UserAccount.email,
                    models.UserAccount.is_admin,
                )
            )
            return [AccountRef(id=row[0], email=row[1], is_admin=row[2]) for row in rows]


class SyncReportSendRepository:
    """Creates the server-owned report rows the cycle hands to the existing ``deliver`` task."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_report_delivery(self, *, to_email: str, subject: str, body: str, png: bytes) -> UUID:
        with self._session_factory() as session:
            dispatch = models.Dispatch(
                user_id=None,
                channel=Channel.REPORT.value,
                title=subject,
                content=body,
                attachment_png=png,
            )
            session.add(dispatch)
            session.flush()
            delivery = models.Delivery(
                dispatch_id=dispatch.id,
                contact_id=None,
                recipient_name=to_email,
                destination=to_email,
                status=DeliveryStatus.QUEUED.value,
            )
            session.add(delivery)
            session.flush()
            session.add(
                models.DeliveryTransition(
                    delivery_id=delivery.id,
                    from_status=None,
                    to_status=DeliveryStatus.QUEUED.value,
                )
            )
            session.commit()
            return delivery.id
