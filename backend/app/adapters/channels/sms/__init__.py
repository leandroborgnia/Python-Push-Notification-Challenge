from __future__ import annotations

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


class SimulatedSmsChannel:
    """SMS channel (ChannelPort). Length is enforced at template save; confirmation is POLLed."""

    channel = Channel.SMS

    def __init__(self, provider: ProviderClient) -> None:
        self._provider = provider

    def destination_of(self, contact: ContactSnapshot) -> str | None:
        return contact.phone

    def validate(self, destination: str, payload: Payload) -> None:
        if not destination.strip():
            raise ChannelValidationError(FailureReason.INVALID_FORMAT.value)

    def send(self, destination: str, payload: Payload, idempotency_key: str) -> SendResult:
        provider_ref = self._provider.send(
            channel=self.channel.value,
            destination=destination,
            payload={"title": payload.title, "content": payload.content},
            idempotency_key=idempotency_key,
        )
        return SendResult(provider_ref=provider_ref)

    def confirmation_mode(self) -> ConfirmationMode:
        return ConfirmationMode.POLL

    def poll_status(self, provider_ref: str) -> PollOutcome:
        status, reason = self._provider.sms_status(provider_ref)
        return PollOutcome(PollStatus(status), reason)
