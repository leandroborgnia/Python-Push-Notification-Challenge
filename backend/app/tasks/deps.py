from __future__ import annotations

from dataclasses import dataclass

from app.adapters.persistence.sync_repo import (
    SyncDeliveryRepository,
    SyncDispatchReader,
    SyncIdempotencyKeyRepository,
)
from app.adapters.resilience.breaker import PyBreakerCircuitBreaker
from app.application.confirmation import SmsPollService
from app.application.delivery import DeliveryService
from app.application.resilience import ResiliencePolicy
from app.bootstrap import build_channel_registry
from app.domain.channels import Channel
from app.infra.db.sync_engine import get_sync_sessionmaker
from app.ports.channels import ChannelPort
from app.settings import Settings, get_settings


@dataclass(frozen=True, slots=True)
class WorkerContainer:
    """Worker-side composition (SYNC engine). Built ONCE per worker process so the breaker registry
    keeps its state across tasks (constitution III/IV)."""

    settings: Settings
    channels: dict[Channel, ChannelPort]
    dispatches: SyncDispatchReader
    deliveries: SyncDeliveryRepository
    delivery: DeliveryService
    sms_poll: SmsPollService


_container: WorkerContainer | None = None


def build_worker_container() -> WorkerContainer:
    settings = get_settings()
    session_factory = get_sync_sessionmaker()
    channels = build_channel_registry(settings)
    breakers = PyBreakerCircuitBreaker(
        fail_max=settings.breaker_fail_max, reset_timeout=settings.breaker_reset_timeout_s
    )
    resilience = ResiliencePolicy(
        breakers=breakers,
        max_attempts=settings.retry_max_attempts,
        backoff_base_s=settings.retry_backoff_base_s,
    )
    deliveries = SyncDeliveryRepository(session_factory)
    dispatches = SyncDispatchReader(session_factory)
    delivery = DeliveryService(
        deliveries=deliveries,
        dispatches=dispatches,
        idempotency=SyncIdempotencyKeyRepository(session_factory),
        channels=channels,
        resilience=resilience,
    )
    sms_poll = SmsPollService(deliveries=deliveries, channels=channels)
    return WorkerContainer(
        settings=settings,
        channels=channels,
        dispatches=dispatches,
        deliveries=deliveries,
        delivery=delivery,
        sms_poll=sms_poll,
    )


def get_worker_container() -> WorkerContainer:
    global _container
    if _container is None:
        _container = build_worker_container()
    return _container


def reset_worker_container() -> None:
    """Test hook — drop the cached container (e.g. after pointing settings at a test provider)."""
    global _container
    _container = None
