from __future__ import annotations

from typing import Protocol

from app.domain.health import SubsystemCheck


class DataStoreProbe(Protocol):
    """Shallow data-store connectivity probe (SELECT 1) via the async data layer."""

    async def check(self) -> SubsystemCheck: ...


class BrokerProbe(Protocol):
    """Message-broker reachability probe."""

    async def check(self) -> SubsystemCheck: ...


class WorkerProbe(Protocol):
    """Per-pool worker liveness ping; returns one check per background-processing pool."""

    async def check(self) -> list[SubsystemCheck]: ...
