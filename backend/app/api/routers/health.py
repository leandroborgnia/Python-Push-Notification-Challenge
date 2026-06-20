from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from opentelemetry import trace

from app.api.deps import get_container
from app.api.schemas import LiveResponse, ReadinessReportOut, ReadyResponse
from app.bootstrap import Container

router = APIRouter(tags=["health"])
_tracer = trace.get_tracer("app.api.health")

ContainerDep = Annotated[Container, Depends(get_container)]


@router.get("/livez", response_model=LiveResponse)
async def livez(container: ContainerDep) -> LiveResponse:
    """Liveness probe — process only; never touches DB/broker/workers (FR-018)."""
    container.liveness.alive()
    return LiveResponse()


@router.get("/readyz", response_model=ReadyResponse)
async def readyz(container: ContainerDep, response: Response) -> ReadyResponse:
    """Readiness probe — process + data store; 503 depools without restart (FR-020)."""
    if await container.readiness.ready():
        return ReadyResponse(status="ready")
    response.status_code = 503
    return ReadyResponse(status="not_ready", detail="data store unreachable")


@router.get("/health", response_model=ReadinessReportOut)
async def health(container: ContainerDep, response: Response) -> ReadinessReportOut:
    """Aggregate health — DB + broker + per-pool worker pings; 200/503 (FR-001/002)."""
    with _tracer.start_as_current_span("health.aggregate"):
        report = await container.aggregate.report()
    if not report.healthy:
        response.status_code = 503
    return ReadinessReportOut.from_domain(report)
