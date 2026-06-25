from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import ContainerDep, CurrentUser
from app.api.schemas import (
    DeliveryStatusOut,
    DispatchAck,
    DispatchStatusOut,
    TransitionOut,
)
from app.application.sending import DispatchView

router = APIRouter(prefix="/api/v1", tags=["sends"])


def _to_status(view: DispatchView) -> DispatchStatusOut:
    return DispatchStatusOut(
        dispatch_id=view.dispatch.id,
        channel=view.dispatch.channel,
        created_at=view.dispatch.created_at,
        deliveries=[
            DeliveryStatusOut(
                delivery_id=d.delivery.id,
                recipient_name=d.delivery.recipient_name,
                destination=d.delivery.destination,
                status=d.delivery.status.value,
                failure_reason=d.delivery.failure_reason,
                transitions=[
                    TransitionOut(
                        from_status=t.from_status.value if t.from_status else None,
                        to_status=t.to_status.value,
                        reason=t.reason,
                        attempt=t.attempt,
                        at=t.at,
                    )
                    for t in d.transitions
                ],
            )
            for d in view.deliveries
        ],
    )


@router.post(
    "/templates/{template_id}/send",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DispatchAck,
)
async def send_template(
    template_id: UUID, container: ContainerDep, user_id: CurrentUser
) -> DispatchAck:
    """Send a valid template; immediate accept, background delivery (FR-019/020). 400 if invalid to
    send (no recipients / unsupported channel, FR-029); 404 if not owned."""
    dispatch_id = await container.sending.send_template(user_id, template_id)
    return DispatchAck(dispatch_id=dispatch_id)


@router.get("/sends", response_model=list[DispatchStatusOut])
async def list_sends(
    container: ContainerDep,
    user_id: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DispatchStatusOut]:
    """List the caller's own dispatches with per-recipient status (FR-027)."""
    views = await container.send_query.list_for_owner(user_id, limit=limit, offset=offset)
    return [_to_status(view) for view in views]


@router.get("/sends/{dispatch_id}", response_model=DispatchStatusOut)
async def get_send(
    dispatch_id: UUID, container: ContainerDep, user_id: CurrentUser
) -> DispatchStatusOut:
    """One dispatch's per-recipient outcomes + transitions (FR-027, SC-006). 404 if not owned."""
    view = await container.send_query.get_for_owner(user_id, dispatch_id)
    return _to_status(view)
