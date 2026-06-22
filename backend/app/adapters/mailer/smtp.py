from __future__ import annotations

from email.message import EmailMessage

import aiosmtplib

from app.settings import Settings


class SmtpMailer:
    """`Mailer` port impl using aiosmtplib — a real, direct SMTP send (dev points at Mailpit)."""

    def __init__(self, settings: Settings) -> None:
        self._host = settings.smtp_host
        self._port = settings.smtp_port
        self._from = settings.mail_from

    async def send_verification(self, email: str, token: str) -> None:
        await self._send(
            email,
            "Verify your account",
            f"Welcome! Confirm your account with this verification token:\n\n{token}\n",
        )

    async def send_reset(self, email: str, token: str) -> None:
        await self._send(
            email,
            "Reset your password",
            f"Use this token to set a new password:\n\n{token}\n",
        )

    async def _send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        await aiosmtplib.send(message, hostname=self._host, port=self._port)
