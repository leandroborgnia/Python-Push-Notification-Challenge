from __future__ import annotations

import asyncio
from collections.abc import Awaitable

from app.domain.health import ReadinessReport, SubsystemCheck, SubsystemName
from app.ports.probes import BrokerProbe, DataStoreProbe, WorkerProbe


class AggregateReadinessService:
    """GET /health: shallow DB + broker + per-pool worker checks, concurrent and bounded.

    Never enqueues or awaits a background job (FR-004/FR-014); each check is time-bounded so
    the endpoint returns promptly even when a dependency is failing (FR-006).
    """

    def __init__(
        self,
        data_store: DataStoreProbe,
        broker: BrokerProbe,
        worker: WorkerProbe,
        timeout: float,
    ) -> None:
        self._data_store = data_store
        self._broker = broker
        self._worker = worker
        self._timeout = timeout

    async def _single(self, coro: Awaitable[SubsystemCheck], name: SubsystemName) -> SubsystemCheck:
        try:
            return await asyncio.wait_for(coro, timeout=self._timeout)
        except TimeoutError:
            return SubsystemCheck(name, passed=False, detail="timeout")

    async def _workers(self) -> list[SubsystemCheck]:
        try:
            return await asyncio.wait_for(self._worker.check(), timeout=self._timeout)
        except TimeoutError:
            return [
                SubsystemCheck(SubsystemName.WORKER_POOL_CPU, passed=False, detail="timeout"),
                SubsystemCheck(SubsystemName.WORKER_POOL_IO, passed=False, detail="timeout"),
            ]

    async def report(self) -> ReadinessReport:
        data_store, broker, workers = await asyncio.gather(
            self._single(self._data_store.check(), SubsystemName.DATA_STORE),
            self._single(self._broker.check(), SubsystemName.MESSAGE_BROKER),
            self._workers(),
        )
        return ReadinessReport(checks=(data_store, broker, *workers))
