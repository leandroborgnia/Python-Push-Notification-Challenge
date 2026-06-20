from __future__ import annotations

import asyncio

from celery import Celery

from app.domain.health import SubsystemCheck, SubsystemName

# Map worker nodename prefix (`-n cpu@%h` / `-n io@%h`) → subsystem.
_POOL_SUBSYSTEM: dict[str, SubsystemName] = {
    "cpu": SubsystemName.WORKER_POOL_CPU,
    "io": SubsystemName.WORKER_POOL_IO,
}


class CeleryWorkerProbe:
    """Per-pool worker liveness via control ping, grouped by nodename prefix."""

    def __init__(self, app: Celery, timeout: float) -> None:
        self._app = app
        self._timeout = timeout

    def _responding_pools_sync(self) -> set[str]:
        replies: list[dict[str, object]] = self._app.control.ping(timeout=self._timeout) or []
        pools: set[str] = set()
        for reply in replies:
            for nodename in reply:
                prefix = nodename.split("@", 1)[0]
                if prefix in _POOL_SUBSYSTEM:
                    pools.add(prefix)
        return pools

    async def check(self) -> list[SubsystemCheck]:
        try:
            responding = await asyncio.to_thread(self._responding_pools_sync)
        except Exception as exc:  # noqa: BLE001 - health probe reports any failure
            return [
                SubsystemCheck(subsystem, passed=False, detail=str(exc))
                for subsystem in _POOL_SUBSYSTEM.values()
            ]
        return [
            SubsystemCheck(
                subsystem,
                passed=prefix in responding,
                detail=None if prefix in responding else "no worker responded",
            )
            for prefix, subsystem in _POOL_SUBSYSTEM.items()
        ]
