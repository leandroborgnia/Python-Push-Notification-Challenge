from __future__ import annotations


class DomainError(Exception):
    """Base for all domain-level errors (framework-free; mapped to HTTP at the API edge)."""


class ValidationError(DomainError):
    """A value violates a domain rule (maps to 422 at the API)."""


class NotFoundError(DomainError):
    """A resource does not exist or is not visible to the caller (maps to 404, SC-003)."""


class ForbiddenError(DomainError):
    """The caller is authenticated but not allowed to act (maps to 403/404 per policy)."""


class ConflictError(DomainError):
    """A uniqueness rule is violated, e.g. duplicate email at registration (maps to 409, FR-001)."""


class AuthenticationError(DomainError):
    """Bad credentials or an unverified account at login (maps to 400, FR-004)."""


class TokenError(DomainError):
    """An email verification/reset token is invalid, expired, or already consumed (maps to 400)."""


class InvalidSendError(DomainError):
    """A template cannot be sent (no recipients / unsupported channel) — FR-029 (maps to 400)."""


class ChannelValidationError(DomainError):
    """Pre-send, channel-specific validation failed (e.g. bad email/device token).

    Drives a direct ``queued -> failed`` transition with a recorded reason (FR-022); never reaches
    ``sent``.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class TransientChannelError(DomainError):
    """A retryable provider failure (429 / timeout / 5xx) — drives retry/backoff + breaker."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class PermanentChannelError(DomainError):
    """A non-retryable provider failure — fail the delivery without further retries."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
