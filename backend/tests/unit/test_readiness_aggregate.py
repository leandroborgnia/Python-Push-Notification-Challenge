from __future__ import annotations

import asyncio

import pytest

from app.application.readiness_aggregate import AggregateReadinessService
from app.domain.health import HealthStatus, SubsystemCheck, SubsystemName


class FakeDataStore:
    def __init__(self, ok: bool) -> None:
        self.ok = ok

    async def check(self) -> SubsystemCheck:
        return SubsystemCheck(SubsystemName.DATA_STORE, passed=self.ok)


class FakeBroker:
    def __init__(self, ok: bool) -> None:
        self.ok = ok

    async def check(self) -> SubsystemCheck:
        return SubsystemCheck(SubsystemName.MESSAGE_BROKER, passed=self.ok)


class FakeWorker:
    def __init__(self, cpu: bool, io: bool) -> None:
        self.cpu = cpu
        self.io = io

    async def check(self) -> list[SubsystemCheck]:
        return [
            SubsystemCheck(SubsystemName.WORKER_POOL_CPU, passed=self.cpu),
            SubsystemCheck(SubsystemName.WORKER_POOL_IO, passed=self.io),
        ]


def _service(ds=True, broker=True, cpu=True, io=True, timeout=2.0):
    return AggregateReadinessService(
        FakeDataStore(ds), FakeBroker(broker), FakeWorker(cpu, io), timeout=timeout
    )


async def test_all_pass_is_healthy():
    report = await _service().report()
    assert report.status is HealthStatus.HEALTHY
    assert len(report.checks) == 4
    assert all(check.passed for check in report.checks)


@pytest.mark.parametrize(
    ("ds", "broker", "cpu", "io"),
    [
        (False, True, True, True),
        (True, False, True, True),
        (True, True, False, True),
        (True, True, True, False),
    ],
)
async def test_any_failure_is_not_healthy(ds, broker, cpu, io):
    report = await _service(ds=ds, broker=broker, cpu=cpu, io=io).report()
    assert report.status is HealthStatus.NOT_HEALTHY


async def test_bounded_when_a_check_hangs():
    class HangingBroker:
        async def check(self) -> SubsystemCheck:
            await asyncio.sleep(10)
            return SubsystemCheck(SubsystemName.MESSAGE_BROKER, passed=True)

    service = AggregateReadinessService(
        FakeDataStore(True), HangingBroker(), FakeWorker(True, True), timeout=0.2
    )
    report = await asyncio.wait_for(service.report(), timeout=2.0)
    broker = next(c for c in report.checks if c.name is SubsystemName.MESSAGE_BROKER)
    assert not broker.passed
    assert broker.detail == "timeout"


async def test_readiness_path_enqueues_no_task(monkeypatch):
    # FR-015: the always-on readiness path must never enqueue a background job.
    from app.tasks import liveness

    calls: list[object] = []
    monkeypatch.setattr(liveness.liveness_ping, "apply_async", lambda *a, **k: calls.append((a, k)))
    await _service().report()
    assert calls == []
