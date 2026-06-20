from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.adapters.persistence.models import LivenessCompletion


class SyncLivenessCompletionWriter:
    """Implements LivenessCompletionWriter using the synchronous (psycopg) engine."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def record(self, correlation_id: UUID, pool_label: str) -> None:
        with self._session_factory() as session:
            session.add(LivenessCompletion(correlation_id=correlation_id, pool_label=pool_label))
            session.commit()
