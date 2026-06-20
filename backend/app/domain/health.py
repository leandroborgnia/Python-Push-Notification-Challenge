from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    NOT_HEALTHY = "not_healthy"


class SubsystemName(StrEnum):
    DATA_STORE = "data_store"
    MESSAGE_BROKER = "message_broker"
    WORKER_POOL_CPU = "worker_pool_cpu"
    WORKER_POOL_IO = "worker_pool_io"


@dataclass(frozen=True, slots=True)
class SubsystemCheck:
    """Result of one shallow connectivity check inside the aggregate readiness report."""

    name: SubsystemName
    passed: bool
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    """Aggregate verdict returned by GET /health (binary; no degraded state in this slice)."""

    checks: tuple[SubsystemCheck, ...]
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def status(self) -> HealthStatus:
        return HealthStatus.HEALTHY if self.healthy else HealthStatus.NOT_HEALTHY

    @property
    def healthy(self) -> bool:
        return all(check.passed for check in self.checks)
