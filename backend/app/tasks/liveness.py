from __future__ import annotations

from uuid import UUID

from app.adapters.persistence.sync_repo import SyncLivenessCompletionWriter
from app.infra.db.sync_engine import get_sync_sessionmaker
from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.liveness.liveness_ping")
def liveness_ping(correlation_id: str, pool_label: str) -> None:
    """Trivial no-op task; records a completion row via the synchronous engine (FR-009)."""
    writer = SyncLivenessCompletionWriter(get_sync_sessionmaker())
    writer.record(UUID(correlation_id), pool_label)
