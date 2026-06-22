"""In-test fakes for ports that must NOT do real I/O during the suite."""

from __future__ import annotations


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
