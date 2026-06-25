from __future__ import annotations

from uuid import UUID

import pybreaker
import structlog
from opentelemetry import trace

from app.application.resilience import IdempotencyGuard, ResiliencePolicy
from app.domain.channels import Channel
from app.domain.dispatch import DeliveryStatus, FailureReason
from app.domain.errors import (
    ChannelValidationError,
    PermanentChannelError,
    TransientChannelError,
)
from app.ports.channels import ChannelPort, Payload
from app.ports.repositories import (
    IdempotencyKeyRepository,
    SyncDeliveryRepository,
    SyncDispatchReader,
)

_log = structlog.get_logger("app.delivery")
_tracer = trace.get_tracer("app.application.delivery")


class DeliveryService:
    """Deliver one recipient (worker, sync). Pre-send validation fails directly to ``queued→failed``
    (FR-022); otherwise claim the idempotency key, then send under breaker+retry and record
    ``queued→sent``. Resilience lives here, never in the channel adapter (Principle IV)."""

    def __init__(
        self,
        *,
        deliveries: SyncDeliveryRepository,
        dispatches: SyncDispatchReader,
        idempotency: IdempotencyKeyRepository,
        channels: dict[Channel, ChannelPort],
        resilience: ResiliencePolicy,
    ) -> None:
        self._deliveries = deliveries
        self._dispatches = dispatches
        self._guard = IdempotencyGuard(idempotency)
        self._channels = channels
        self._resilience = resilience

    def deliver_one(self, delivery_id: UUID) -> DeliveryStatus | None:
        with _tracer.start_as_current_span("deliver.one") as span:
            span.set_attribute("delivery.id", str(delivery_id))
            return self._deliver_one(delivery_id, span)

    def _deliver_one(self, delivery_id: UUID, span: trace.Span) -> DeliveryStatus | None:
        delivery = self._deliveries.get(delivery_id)
        if delivery is None or delivery.status is not DeliveryStatus.QUEUED:
            return None  # already processed or unknown → idempotent no-op
        dispatch = self._dispatches.get(delivery.dispatch_id)
        if dispatch is None:
            return None
        span.set_attribute("delivery.channel", dispatch.channel.value)
        adapter = self._channels[dispatch.channel]
        # One-time additive change: thread the dispatch attachment (the report PNG) through the
        # shared flow; existing channels leave attachment None and ignore it (SC-010).
        payload = Payload(
            title=dispatch.title, content=dispatch.content, attachment=dispatch.attachment
        )

        # Pre-send validation → direct queued→failed, never 'sent' (FR-022).
        destination = delivery.destination
        if not destination:
            _log.info(
                "delivery_failed",
                delivery_id=str(delivery_id),
                channel=dispatch.channel.value,
                reason=FailureReason.MISSING_DESTINATION.value,
            )
            self._deliveries.record_failed(
                delivery_id, reason=FailureReason.MISSING_DESTINATION.value, attempt=None
            )
            return DeliveryStatus.FAILED
        try:
            adapter.validate(destination, payload)
        except ChannelValidationError as exc:
            _log.info(
                "delivery_failed",
                delivery_id=str(delivery_id),
                channel=dispatch.channel.value,
                reason=exc.reason,
            )
            self._deliveries.record_failed(delivery_id, reason=exc.reason, attempt=None)
            return DeliveryStatus.FAILED

        # Idempotency: claim before the provider call; a lost race means we must not send again.
        if not self._guard.claim(delivery_id):
            return None

        breaker_key = f"{dispatch.channel.value}:{destination}"
        idempotency_key = IdempotencyGuard.key_for(delivery_id)
        try:
            result = self._resilience.run(
                breaker_key, lambda: adapter.send(destination, payload, idempotency_key)
            )
        except (TransientChannelError, PermanentChannelError, pybreaker.CircuitBreakerError) as exc:
            _log.info(
                "delivery_failed",
                delivery_id=str(delivery_id),
                channel=dispatch.channel.value,
                reason=FailureReason.CHANNEL_ERROR.value,
                error=str(exc),
            )
            self._deliveries.record_failed(
                delivery_id, reason=FailureReason.CHANNEL_ERROR.value, attempt=None
            )
            return DeliveryStatus.FAILED

        self._deliveries.record_sent(delivery_id, provider_ref=result.provider_ref, attempt=None)
        _log.info(
            "delivery_sent",
            delivery_id=str(delivery_id),
            channel=dispatch.channel.value,
            provider_ref=result.provider_ref,
        )
        return DeliveryStatus.SENT
