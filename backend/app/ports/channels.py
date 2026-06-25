from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.domain.channels import Channel


class ConfirmationMode(StrEnum):
    """How a channel's terminal outcome arrives back to us."""

    WEBHOOK = "webhook"  # email/push — provider POSTs us a callback
    POLL = "poll"  # sms — we poll a provider status endpoint


class PollStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ContactSnapshot:
    """The recipient's destinations at send time (the dispatcher snapshots from this)."""

    display_name: str
    email: str | None = None
    phone: str | None = None
    device_token: str | None = None


@dataclass(frozen=True, slots=True)
class Payload:
    """The rendered, snapshotted message handed to the provider.

    ``attachment`` is a one-time additive capability (e.g. the report PNG); existing channel
    adapters ignore it (SC-010) — only the report channel reads it.
    """

    title: str
    content: str
    attachment: bytes | None = None
    attachment_name: str = "report.png"


@dataclass(frozen=True, slots=True)
class SendResult:
    """Returned when the provider accepts the outbound call (delivery → ``sent``)."""

    provider_ref: str


@dataclass(frozen=True, slots=True)
class PollOutcome:
    status: PollStatus
    reason: str | None = None


class ChannelPort(Protocol):
    """The single strategy seam every channel implements (constitution II, FR-028 / SC-008).

    Adding a channel = one new adapter implementing this + a binding in bootstrap; no existing
    channel adapter or the shared dispatch/resilience flow may change.
    """

    channel: Channel

    def destination_of(self, contact: ContactSnapshot) -> str | None:
        """The channel-relevant destination, or None if absent (→ failed: missing_destination)."""
        ...

    def validate(self, destination: str, payload: Payload) -> None:
        """Pre-send, channel-specific validation. Raise ChannelValidationError(reason) to fail a
        delivery before ``sent`` (e.g. email format, push device-token)."""
        ...

    def send(self, destination: str, payload: Payload, idempotency_key: str) -> SendResult:
        """Hand the message to the provider over HTTP. Returns SendResult on accept; raises
        TransientChannelError (429/timeout/5xx) to drive retry/backoff/breaker, or
        PermanentChannelError to fail. Idempotent w.r.t. ``idempotency_key``."""
        ...

    def confirmation_mode(self) -> ConfirmationMode:
        """WEBHOOK (email/push) or POLL (sms)."""
        ...

    def poll_status(self, provider_ref: str) -> PollOutcome:
        """POLL channels only: query provider status → DELIVERED | FAILED(reason) | PENDING."""
        ...
