from __future__ import annotations

from uuid import UUID

import structlog
from opentelemetry import trace

from app.domain.channels import Channel
from app.domain.dispatch import DeliveryStatus
from app.ports.channels import ChannelPort, PollStatus
from app.ports.repositories import DeliveryRepository, SyncDeliveryRepository

_log = structlog.get_logger("app.confirmation")
_tracer = trace.get_tracer("app.application.confirmation")


class WebhookConfirmationService:
    """Apply an email/push delivery confirmation that the provider POSTed to our webhook (async).
    Correlated by ``provider_ref`` and idempotent: an unknown ref or an already-terminal delivery is
    ignored with no state change (FR-025/FR-031)."""

    def __init__(self, deliveries: DeliveryRepository) -> None:
        self._deliveries = deliveries

    async def apply(
        self, provider_ref: str, outcome: DeliveryStatus, reason: str | None = None
    ) -> bool:
        with _tracer.start_as_current_span("confirm.webhook") as span:
            span.set_attribute("confirm.provider_ref", provider_ref)
            span.set_attribute("confirm.outcome", outcome.value)
            applied = await self._deliveries.confirm_by_provider_ref(provider_ref, outcome, reason)
            span.set_attribute("confirm.applied", applied)
            _log.info(
                "webhook_confirmation",
                provider_ref=provider_ref,
                outcome=outcome.value,
                applied=applied,  # False = duplicate/uncorrelated → no state change (idempotent)
            )
            return applied


class SmsPollService:
    """Poll the provider for an SMS delivery's terminal outcome (worker, sync). Returns ``True``
    when polling should stop (terminal outcome recorded, or the delivery is no longer ``sent``)."""

    def __init__(
        self,
        *,
        deliveries: SyncDeliveryRepository,
        channels: dict[Channel, ChannelPort],
    ) -> None:
        self._deliveries = deliveries
        self._channels = channels

    def poll_once(self, delivery_id: UUID) -> bool:
        with _tracer.start_as_current_span("confirm.poll") as span:
            span.set_attribute("delivery.id", str(delivery_id))
            delivery = self._deliveries.get(delivery_id)
            if (
                delivery is None
                or delivery.status is not DeliveryStatus.SENT
                or not delivery.provider_ref
            ):
                return True  # nothing to poll
            outcome = self._channels[Channel.SMS].poll_status(delivery.provider_ref)
            span.set_attribute("confirm.poll_status", outcome.status.value)
            if outcome.status is PollStatus.DELIVERED:
                self._deliveries.confirm(delivery_id, outcome=DeliveryStatus.DELIVERED, reason=None)
                _log.info("sms_poll_confirmed", delivery_id=str(delivery_id), outcome="delivered")
                return True
            if outcome.status is PollStatus.FAILED:
                self._deliveries.confirm(
                    delivery_id, outcome=DeliveryStatus.FAILED, reason=outcome.reason
                )
                _log.info(
                    "sms_poll_confirmed",
                    delivery_id=str(delivery_id),
                    outcome="failed",
                    reason=outcome.reason,
                )
                return True
            return False  # still pending → caller re-enqueues within the window
