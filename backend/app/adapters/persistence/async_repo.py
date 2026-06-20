from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.persistence.models import LivenessCompletion

_REQUIRED_POOLS = frozenset({"cpu", "io"})


class AsyncLivenessCompletionReader:
    """Implements LivenessCompletionReader using the async (asyncpg) engine."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def completed_pools(self, correlation_id: UUID) -> set[str]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(LivenessCompletion.pool_label).where(
                    LivenessCompletion.correlation_id == correlation_id
                )
            )
            return set(result.scalars().all())

    async def both_completed(self, correlation_id: UUID) -> bool:
        return await self.completed_pools(correlation_id) >= _REQUIRED_POOLS
