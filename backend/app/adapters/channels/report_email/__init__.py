from __future__ import annotations

import re
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid

from app.domain.channels import Channel
from app.domain.dispatch import FailureReason
from app.domain.errors import (
    ChannelValidationError,
    PermanentChannelError,
    TransientChannelError,
)
from app.ports.channels import (
    ConfirmationMode,
    ContactSnapshot,
    Payload,
    PollOutcome,
    PollStatus,
    SendResult,
)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SmtpReportEmailChannel:
    """Report-email channel (ChannelPort, ``Channel.REPORT``) — a real stdlib ``smtplib`` sender
    that attaches the rendered PNG. Runs through the existing resilient delivery pipeline; the
    report rests at ``sent`` because no webhook arrives (WEBHOOK mode). Deliberately the seed of the
    future real (non-simulated) email channel. **Do not edit the simulated channel adapters.**"""

    channel = Channel.REPORT

    def __init__(self, *, host: str, port: int, mail_from: str) -> None:
        self._host = host
        self._port = port
        self._mail_from = mail_from

    def destination_of(self, contact: ContactSnapshot) -> str | None:
        # n/a — the cycle sets delivery.destination to the account's own email directly.
        return contact.email

    def validate(self, destination: str, payload: Payload) -> None:
        if not _EMAIL_RE.match(destination):
            raise ChannelValidationError(FailureReason.INVALID_FORMAT.value)

    def send(self, destination: str, payload: Payload, idempotency_key: str) -> SendResult:
        message = EmailMessage()
        message_id = make_msgid()
        message["Message-ID"] = message_id
        message["From"] = self._mail_from
        message["To"] = destination
        message["Subject"] = payload.title
        message.set_content(payload.content)
        if payload.attachment is not None:
            message.add_attachment(
                payload.attachment,
                maintype="image",
                subtype="png",
                filename=payload.attachment_name,
            )
        try:
            with smtplib.SMTP(self._host, self._port, timeout=10) as smtp:
                smtp.send_message(message)
        except smtplib.SMTPResponseException as exc:
            # 5xx = permanent (bad recipient/sender, policy); 4xx/other = transient (retry/backoff).
            if exc.smtp_code is not None and exc.smtp_code >= 500:
                raise PermanentChannelError(str(exc)) from exc
            raise TransientChannelError(str(exc)) from exc
        except (smtplib.SMTPException, OSError) as exc:
            # Connection refused, disconnect, timeout — retryable.
            raise TransientChannelError(str(exc)) from exc
        return SendResult(provider_ref=message_id)

    def confirmation_mode(self) -> ConfirmationMode:
        return ConfirmationMode.WEBHOOK  # no webhook arrives → the report rests at 'sent'

    def poll_status(self, provider_ref: str) -> PollOutcome:
        return PollOutcome(PollStatus.PENDING)  # n/a — report is never polled
