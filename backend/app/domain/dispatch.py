from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.channels import Channel
from app.domain.errors import ValidationError


class DeliveryStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"


class FailureReason(StrEnum):
    MISSING_DESTINATION = "missing_destination"
    INVALID_FORMAT = "invalid_format"
    INVALID_DEVICE_TOKEN = "invalid_device_token"
    CHANNEL_ERROR = "channel_error"


@dataclass(frozen=True, slots=True)
class Dispatch:
    """A standalone send snapshot — holds NO link to the source template (FR-030).

    ``user_id`` is ``None`` for a server-originated send (a stats report); user sends always set it.
    """

    id: UUID
    user_id: UUID | None
    channel: Channel
    title: str
    content: str
    created_at: datetime | None = None
    attachment: bytes | None = None  # the report PNG for server-originated sends (004)


@dataclass(frozen=True, slots=True)
class Delivery:
    """A per-recipient send record (current state; full history in transitions)."""

    id: UUID
    dispatch_id: UUID
    recipient_name: str
    status: DeliveryStatus
    destination: str | None = None
    failure_reason: str | None = None
    provider_ref: str | None = None
    contact_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class Transition:
    """One append-only lifecycle edge (FR-025)."""

    from_status: DeliveryStatus | None
    to_status: DeliveryStatus
    reason: str | None = None
    attempt: int | None = None
    at: datetime | None = None


# Legal lifecycle edges (data-model state machine). `queued → failed` is the direct edge taken on
# pre-send validation failure; there is no `skipped` state and no terminal-state overwrite.
_ALLOWED_TRANSITIONS: frozenset[tuple[DeliveryStatus, DeliveryStatus]] = frozenset(
    {
        (DeliveryStatus.QUEUED, DeliveryStatus.SENT),
        (DeliveryStatus.QUEUED, DeliveryStatus.FAILED),
        (DeliveryStatus.SENT, DeliveryStatus.DELIVERED),
        (DeliveryStatus.SENT, DeliveryStatus.FAILED),
    }
)


def is_terminal(status: DeliveryStatus) -> bool:
    return status in (DeliveryStatus.DELIVERED, DeliveryStatus.FAILED)


def validate_transition(from_status: DeliveryStatus, to_status: DeliveryStatus) -> None:
    """Raise if ``from_status → to_status`` is not a legal, non-overwriting edge (Principle IV)."""
    if (from_status, to_status) not in _ALLOWED_TRANSITIONS:
        raise ValidationError(f"illegal delivery transition: {from_status} -> {to_status}")
