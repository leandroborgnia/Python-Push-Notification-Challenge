from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.persistence import models
from app.adapters.persistence.models import LivenessCompletion
from app.domain.channels import Channel
from app.domain.dispatch import Delivery, DeliveryStatus, Dispatch


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
