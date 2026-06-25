"""In-test fakes for ports that must NOT do real I/O during the suite."""

from __future__ import annotations

from app.domain.channels import Channel
from app.domain.errors import TransientChannelError
from app.ports.channels import (
    ConfirmationMode,
    ContactSnapshot,
    Payload,
    PollOutcome,
    PollStatus,
    SendResult,
)


class FailingReportChannel:
    """A report ``ChannelPort`` whose ``send`` raises ``TransientChannelError`` (drives
    retry/backoff → breaker) for destinations in ``failing`` (or all when ``failing`` is None);
    other destinations succeed. Used to prove report-delivery resilience + per-recipient isolation
    in-process, without real SMTP (T031)."""

    channel = Channel.REPORT

    def __init__(self, *, failing: set[str] | None = None) -> None:
        self._failing = failing
        self.sent: list[str] = []
        self.calls: list[str] = []  # every send attempt (incl. failures) → proves retry/backoff

    def destination_of(self, contact: ContactSnapshot) -> str | None:
        return contact.email

    def validate(self, destination: str, payload: Payload) -> None:
        return None

    def send(self, destination: str, payload: Payload, idempotency_key: str) -> SendResult:
        self.calls.append(destination)
        if self._failing is None or destination in self._failing:
            raise TransientChannelError("simulated report SMTP failure")
        self.sent.append(destination)
        return SendResult(provider_ref=f"ok-{destination}")

    def confirmation_mode(self) -> ConfirmationMode:
        return ConfirmationMode.WEBHOOK

    def poll_status(self, provider_ref: str) -> PollOutcome:
        return PollOutcome(PollStatus.PENDING)


class FakeMailer:
    """`Mailer` fake — captures the plaintext token (the only place it exists unhashed) so tests
    can drive the verify/reset flow without real SMTP (research §3)."""

    def __init__(self) -> None:
        self.verifications: list[tuple[str, str]] = []
        self.resets: list[tuple[str, str]] = []

    async def send_verification(self, email: str, token: str) -> None:
        self.verifications.append((email.lower(), token))

    async def send_reset(self, email: str, token: str) -> None:
        self.resets.append((email.lower(), token))

    def verification_token_for(self, email: str) -> str:
        for sent_email, token in reversed(self.verifications):
            if sent_email == email.lower():
                return token
        raise KeyError(f"no verification token sent to {email}")

    def reset_token_for(self, email: str) -> str:
        for sent_email, token in reversed(self.resets):
            if sent_email == email.lower():
                return token
        raise KeyError(f"no reset token sent to {email}")
