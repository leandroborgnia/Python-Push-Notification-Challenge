from __future__ import annotations

from app.ports.probes import DataStoreProbe


class LivenessService:
    """Process-only liveness (FR-018): if this runs, the process is alive."""

    def alive(self) -> bool:
        return True


class ReadinessService:
    """Process + data-store readiness (FR-020): depool on DB outage, never restart."""

    def __init__(self, data_store: DataStoreProbe) -> None:
        self._data_store = data_store

    async def ready(self) -> bool:
        return (await self._data_store.check()).passed
