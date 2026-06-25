from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.domain.errors import ValidationError


@dataclass(frozen=True, slots=True)
class Contact:
    """A private contact in a user's personal book — pure domain shape."""

    id: UUID
    owner_id: UUID
    display_name: str
    email: str | None = None
    phone: str | None = None
    device_token: str | None = None

    @property
    def has_destination(self) -> bool:
        return bool(self.email or self.phone or self.device_token)


def validate_contact_destinations(
    email: str | None, phone: str | None, device_token: str | None
) -> None:
    """Enforce the "≥1 destination" rule at add time (FR-008). Pure — raises on violation."""
    if not (email or phone or device_token):
        raise ValidationError(
            "a contact requires at least one destination (email, phone, or device token)"
        )
