from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from app.domain.channels import Channel
from app.domain.errors import ValidationError

SMS_MAX_LENGTH = 160


@dataclass(frozen=True, slots=True)
class Template:
    """A reusable per-user notification definition — pure domain shape."""

    id: UUID
    owner_id: UUID
    title: str
    content: str
    channel: Channel
    recipient_ids: tuple[UUID, ...] = ()


def parse_channel(value: str) -> Channel:
    """Validate a channel string against the enum (FR-016). Raises on anything unsupported."""
    try:
        return Channel(value)
    except ValueError as exc:
        raise ValidationError(f"unsupported channel: {value!r}") from exc


def validate_sms_length(channel: Channel, content: str) -> None:
    """SMS content must be ≤160 chars, enforced at save (FR-018)."""
    if channel is Channel.SMS and len(content) > SMS_MAX_LENGTH:
        raise ValidationError(f"SMS content must be {SMS_MAX_LENGTH} characters or fewer")


def ensure_recipients_owned(requested_ids: Iterable[UUID], owned_ids: Iterable[UUID]) -> None:
    """Every referenced contact must be owned by the caller (FR-011, Acc US2.5). Pure."""
    missing = set(requested_ids) - set(owned_ids)
    if missing:
        raise ValidationError("one or more recipient contacts are not owned by you")
