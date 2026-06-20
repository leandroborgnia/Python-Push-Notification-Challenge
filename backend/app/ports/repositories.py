from __future__ import annotations

from typing import Protocol
from uuid import UUID


class LivenessCompletionWriter(Protocol):
    """Synchronous writer used by Celery workers (psycopg engine)."""

    def record(self, correlation_id: UUID, pool_label: str) -> None: ...


class LivenessCompletionReader(Protocol):
    """Async reader used by the API / smoke CLI (asyncpg engine)."""

    async def completed_pools(self, correlation_id: UUID) -> set[str]: ...

    async def both_completed(self, correlation_id: UUID) -> bool: ...
