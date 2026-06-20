from __future__ import annotations

import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.health import SubsystemCheck, SubsystemName


class AsyncDataStoreProbe:
    """Shallow data-store connectivity probe (SELECT 1) over the async engine."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def check(self) -> SubsystemCheck:
        start = time.perf_counter()
        try:
            async with self._session_factory() as session:
                await session.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 - health probe reports any failure
            return SubsystemCheck(SubsystemName.DATA_STORE, passed=False, detail=str(exc))
        elapsed_ms = (time.perf_counter() - start) * 1000
        return SubsystemCheck(SubsystemName.DATA_STORE, passed=True, detail=f"{elapsed_ms:.0f}ms")
