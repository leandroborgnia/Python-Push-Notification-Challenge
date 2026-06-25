"""Builders for in-process worker-path tests (deliver_one with respx-mocked provider HTTP)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.channels.email import SimulatedEmailChannel
from app.adapters.channels.provider_http import ProviderClient
from app.adapters.channels.push import SimulatedPushChannel
from app.adapters.channels.sms import SimulatedSmsChannel
from app.adapters.persistence.sync_repo import (
    SyncDeliveryRepository,
    SyncDispatchReader,
    SyncIdempotencyKeyRepository,
)
from app.adapters.resilience.breaker import PyBreakerCircuitBreaker
from app.application.delivery import DeliveryService
from app.application.resilience import ResiliencePolicy
from app.domain.channels import Channel
from app.ports.channels import ChannelPort

PROVIDER_BASE_URL = "http://provider.test"


@dataclass
class InProcessDelivery:
    service: DeliveryService
    deliveries: SyncDeliveryRepository
    breakers: PyBreakerCircuitBreaker


def build_delivery_service(
    session_factory: sessionmaker[Session],
    *,
    max_attempts: int = 3,
    fail_max: int = 5,
    reset_timeout: float = 30.0,
    backoff_base_s: float = 0.0,
) -> InProcessDelivery:
    provider = ProviderClient(PROVIDER_BASE_URL)
    channels: dict[Channel, ChannelPort] = {
        Channel.EMAIL: SimulatedEmailChannel(provider, "http://callback.test/webhook"),
        Channel.SMS: SimulatedSmsChannel(provider),
        Channel.PUSH: SimulatedPushChannel(provider, "http://callback.test/webhook"),
    }
    breakers = PyBreakerCircuitBreaker(fail_max=fail_max, reset_timeout=reset_timeout)
    resilience = ResiliencePolicy(
        breakers=breakers, max_attempts=max_attempts, backoff_base_s=backoff_base_s
    )
    deliveries = SyncDeliveryRepository(session_factory)
    service = DeliveryService(
        deliveries=deliveries,
        dispatches=SyncDispatchReader(session_factory),
        idempotency=SyncIdempotencyKeyRepository(session_factory),
        channels=channels,
        resilience=resilience,
    )
    return InProcessDelivery(service=service, deliveries=deliveries, breakers=breakers)


def poll_deliveries(
    sync_url: str,
    dispatch_id: UUID,
    *,
    until: set[str],
    timeout: float = 30.0,
) -> list[tuple[str, str | None]]:
    """Poll the deliveries of a dispatch (via a fresh sync connection — the worker writes on its
    own connection) until every delivery's status is in ``until``, or the timeout elapses."""
    from app.adapters.persistence.models import Delivery as DeliveryModel

    engine = create_engine(sync_url)
    try:
        deadline = time.time() + timeout
        snapshot: list[tuple[str, str | None]] = []
        while time.time() < deadline:
            with Session(engine) as session:
                rows = (
                    session.execute(
                        select(DeliveryModel).where(DeliveryModel.dispatch_id == dispatch_id)
                    )
                    .scalars()
                    .all()
                )
                snapshot = [(row.status, row.provider_ref) for row in rows]
            if snapshot and all(status in until for status, _ in snapshot):
                return snapshot
            time.sleep(0.3)
        return snapshot
    finally:
        engine.dispose()
