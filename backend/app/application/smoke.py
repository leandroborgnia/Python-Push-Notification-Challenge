from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID, uuid4

from app.ports.repositories import LivenessCompletionReader
from app.tasks.liveness import liveness_ping

_REQUIRED_POOLS = frozenset({"cpu", "io"})
_POLL_INTERVAL_S = 0.2


@dataclass(frozen=True, slots=True)
class SmokeResult:
    ok: bool
    correlation_id: UUID
    completed_pools: set[str]

    @property
    def missing_pools(self) -> set[str]:
        return set(_REQUIRED_POOLS) - self.completed_pools


class SmokeCheckService:
    """On-demand deep round-trip: real task per pool → sync-write → async-read (FR-009)."""

    def __init__(self, reader: LivenessCompletionReader, timeout: float) -> None:
        self._reader = reader
        self._timeout = timeout

    async def run(self) -> SmokeResult:
        correlation_id = uuid4()
        cid = str(correlation_id)
        liveness_ping.apply_async(args=[cid, "cpu"], queue="cpu")
        liveness_ping.apply_async(args=[cid, "io"], queue="io")

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout
        while loop.time() < deadline:
            if await self._reader.both_completed(correlation_id):
                return SmokeResult(True, correlation_id, set(_REQUIRED_POOLS))
            await asyncio.sleep(_POLL_INTERVAL_S)

        completed = await self._reader.completed_pools(correlation_id)
        return SmokeResult(False, correlation_id, completed)
