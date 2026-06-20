from __future__ import annotations

from dataclasses import dataclass

from app.adapters.probes.celery_broker import CeleryBrokerProbe
from app.adapters.probes.celery_worker import CeleryWorkerProbe
from app.adapters.probes.data_store import AsyncDataStoreProbe
from app.application.liveness import LivenessService, ReadinessService
from app.application.readiness_aggregate import AggregateReadinessService
from app.infra.db.async_engine import get_async_sessionmaker
from app.settings import Settings, get_settings
from app.tasks.celery_app import celery_app


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    liveness: LivenessService
    readiness: ReadinessService
    aggregate: AggregateReadinessService


def build_container() -> Container:
    """Composition root: bind ports → adapters."""
    settings = get_settings()
    session_factory = get_async_sessionmaker()

    data_store = AsyncDataStoreProbe(session_factory)
    broker = CeleryBrokerProbe(celery_app, settings.readiness_check_timeout_s)
    worker = CeleryWorkerProbe(celery_app, settings.readiness_check_timeout_s)

    return Container(
        settings=settings,
        liveness=LivenessService(),
        readiness=ReadinessService(data_store),
        aggregate=AggregateReadinessService(
            data_store, broker, worker, settings.readiness_check_timeout_s
        ),
    )
