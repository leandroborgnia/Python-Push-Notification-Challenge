from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.domain.health import HealthStatus, ReadinessReport


class LiveResponse(BaseModel):
    status: str = "alive"


class ReadyResponse(BaseModel):
    status: str
    detail: str | None = None


class SubsystemCheckOut(BaseModel):
    name: str
    passed: bool
    detail: str | None = None


class ReadinessReportOut(BaseModel):
    status: HealthStatus
    checked_at: datetime
    checks: list[SubsystemCheckOut]

    @classmethod
    def from_domain(cls, report: ReadinessReport) -> ReadinessReportOut:
        return cls(
            status=report.status,
            checked_at=report.checked_at,
            checks=[
                SubsystemCheckOut(name=check.name.value, passed=check.passed, detail=check.detail)
                for check in report.checks
            ],
        )
