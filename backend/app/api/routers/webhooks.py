from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.deps import ContainerDep
from app.api.schemas import WebhookConfirmation
from app.domain.dispatch import DeliveryStatus

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


@router.post("/delivery", status_code=status.HTTP_204_NO_CONTENT)
async def delivery_confirmation(body: WebhookConfirmation, container: ContainerDep) -> Response:
    """Provider delivery confirmation for email/push (FR-031). UNAUTHENTICATED machine-to-machine
    (FR-006 exemption); correlated by ``provider_ref`` and idempotent — always 204, even for a
    duplicate or uncorrelated callback (no state change)."""
    outcome = DeliveryStatus.DELIVERED if body.outcome == "delivered" else DeliveryStatus.FAILED
    await container.confirmation.apply(body.provider_ref, outcome, body.reason)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
