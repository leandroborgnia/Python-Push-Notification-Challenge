from __future__ import annotations

import re

from app.adapters.channels.provider_http import ProviderClient
from app.domain.channels import Channel
from app.domain.dispatch import FailureReason
from app.domain.errors import ChannelValidationError
from app.ports.channels import (
    ConfirmationMode,
    ContactSnapshot,
    Payload,
    PollOutcome,
    PollStatus,
    SendResult,
)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SimulatedEmailChannel:
    """Email channel (ChannelPort). Validates address format; confirmation arrives by WEBHOOK."""

    channel = Channel.EMAIL

    def __init__(self, provider: ProviderClient, callback_url: str) -> None:
        self._provider = provider
        self._callback_url = callback_url

    def destination_of(self, contact: ContactSnapshot) -> str | None:
        return contact.email

    def validate(self, destination: str, payload: Payload) -> None:
        if not _EMAIL_RE.match(destination):
            raise ChannelValidationError(FailureReason.INVALID_FORMAT.value)

    def send(self, destination: str, payload: Payload, idempotency_key: str) -> SendResult:
        provider_ref = self._provider.send(
            channel=self.channel.value,
            destination=destination,
            payload={"title": payload.title, "content": payload.content},
            idempotency_key=idempotency_key,
            callback_url=self._callback_url,
        )
        return SendResult(provider_ref=provider_ref)

    def confirmation_mode(self) -> ConfirmationMode:
        return ConfirmationMode.WEBHOOK

    def poll_status(self, provider_ref: str) -> PollOutcome:
        return PollOutcome(PollStatus.PENDING)  # email confirms via webhook, never polled
