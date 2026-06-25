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
        # Base URL of the SPA; the deep-link routes /verify and /reset read ?token=.
        self._app_base_url = settings.app_base_url.rstrip("/")

    async def send_verification(self, email: str, token: str) -> None:
        # token_urlsafe → already URL-safe, so it needs no percent-encoding in the query string.
        link = f"{self._app_base_url}/verify?token={token}"
        await self._send(
            email,
            "Verify your account",
            "Welcome! Confirm your account by opening this link:\n\n"
            f"{link}\n\n"
            f"If the link doesn't work, paste this token into the verification form:\n\n{token}\n",
        )

    async def send_reset(self, email: str, token: str) -> None:
        link = f"{self._app_base_url}/reset?token={token}"
        await self._send(
            email,
            "Reset your password",
            "We received a request to reset your password. Open this link to choose a new one:\n\n"
            f"{link}\n\n"
            f"If the link doesn't work, paste this token into the reset form:\n\n{token}\n",
        )

    async def _send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        await aiosmtplib.send(message, hostname=self._host, port=self._port)
