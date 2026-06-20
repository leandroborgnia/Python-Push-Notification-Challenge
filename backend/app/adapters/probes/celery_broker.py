from __future__ import annotations

import asyncio
import time

from celery import Celery

from app.domain.health import SubsystemCheck, SubsystemName


class CeleryBrokerProbe:
    """Message-broker reachability via kombu connection (blocking call offloaded to a thread)."""

    def __init__(self, app: Celery, timeout: float) -> None:
        self._app = app
        self._timeout = timeout

    def _check_sync(self) -> SubsystemCheck:
        start = time.perf_counter()
        try:
            connection = self._app.connection()
            try:
                connection.ensure_connection(max_retries=0, timeout=self._timeout)
            finally:
                connection.release()
        except Exception as exc:  # noqa: BLE001 - health probe reports any failure
            return SubsystemCheck(SubsystemName.MESSAGE_BROKER, passed=False, detail=str(exc))
        elapsed_ms = (time.perf_counter() - start) * 1000
        return SubsystemCheck(
            SubsystemName.MESSAGE_BROKER, passed=True, detail=f"{elapsed_ms:.0f}ms"
        )

    async def check(self) -> SubsystemCheck:
        return await asyncio.to_thread(self._check_sync)
