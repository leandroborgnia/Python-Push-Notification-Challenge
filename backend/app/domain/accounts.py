from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.errors import TokenError


class TokenPurpose(StrEnum):
    VERIFY = "verify"
    RESET = "reset"


@dataclass(frozen=True, slots=True)
class UserAccount:
    """A registered user — pure domain shape; the password hash never lives here (data-model)."""

    id: UUID
    email: str
    is_verified: bool


@dataclass(slots=True)
class EmailToken:
    """A single-use verification/reset token; validity is purely a function of the clock."""

    id: UUID
    user_id: UUID
    purpose: TokenPurpose
    expires_at: datetime
    consumed_at: datetime | None = None

    def is_valid(self, now: datetime) -> bool:
        return self.consumed_at is None and now < self.expires_at

    def consume(self, now: datetime) -> None:
        """Mark the token used. Raises :class:`TokenError` if already consumed or expired."""
        if self.consumed_at is not None:
            raise TokenError("token already used")
        if now >= self.expires_at:
            raise TokenError("token expired")
        self.consumed_at = now
