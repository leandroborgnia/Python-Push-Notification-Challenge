from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ContainerDep, CurrentAdmin
from app.api.schemas import FrequencyResponse, FrequencyUpdate

router = APIRouter(prefix="/api/v1/admin/stats-report", tags=["admin"])


def _to_response(interval_seconds: int, enabled: bool) -> FrequencyResponse:
    return FrequencyResponse(interval_seconds=interval_seconds, enabled=enabled)


@router.get("/frequency", response_model=FrequencyResponse)
async def get_frequency(container: ContainerDep, admin_id: CurrentAdmin) -> FrequencyResponse:
    """Read the current server-wide report frequency (admin-only, FR-005/FR-007)."""
    view = await container.stats_config.get_frequency()
    return _to_response(view.interval_seconds, view.enabled)


@router.post("/frequency", response_model=FrequencyResponse)
async def set_frequency(
    body: FrequencyUpdate, container: ContainerDep, admin_id: CurrentAdmin
) -> FrequencyResponse:
    """Set the frequency (admin-only). 0 disables; >= 86400 accepted; 1..86399 → 422 with the stored
    value unchanged; the scheduling anchor is reset (FR-005/FR-008/FR-010)."""
    view = await container.stats_config.set_frequency(body.interval_seconds)
    return _to_response(view.interval_seconds, view.enabled)
