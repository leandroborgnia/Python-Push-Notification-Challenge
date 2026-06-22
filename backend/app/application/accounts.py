from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from uuid import UUID

from app.domain.accounts import EmailToken, TokenPurpose, UserAccount
from app.domain.errors import AuthenticationError, ConflictError, TokenError
from app.ports.clock import Clock
from app.ports.mailer import Mailer
from app.ports.repositories import AccountRepository, EmailTokenRepository
from app.ports.security import PasswordHasher, TokenService
from app.settings import Settings


def _hash_token(token: str) -> str:
    """Hash the high-entropy opaque token for storage (argon2 is reserved for low-entropy
    passwords; a random URL-safe token only needs a fast one-way digest)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AccountsService:
    """Register → verify → login → reset orchestration (FR-001..FR-005).

    Verification/reset mail goes out a real, direct SMTP path (the ``Mailer`` port), awaited here —
    never through the Celery dispatch pipeline (research §3).
    """

    def __init__(
        self,
        *,
        accounts: AccountRepository,
        tokens: EmailTokenRepository,
        hasher: PasswordHasher,
        token_service: TokenService,
        mailer: Mailer,
        clock: Clock,
        settings: Settings,
    ) -> None:
        self._accounts = accounts
        self._tokens = tokens
        self._hasher = hasher
        self._token_service = token_service
        self._mailer = mailer
        self._clock = clock
        self._settings = settings

    async def register(self, email: str, password: str) -> UserAccount:
        normalized = email.strip().lower()
        if await self._accounts.email_exists(normalized):
            raise ConflictError("email already registered")
        user = await self._accounts.create(normalized, self._hasher.hash(password))
        await self._issue_email_token(user.id, normalized, TokenPurpose.VERIFY)
        return user

    async def verify_email(self, token: str) -> None:
        email_token = await self._consume(token, TokenPurpose.VERIFY)
        await self._accounts.set_verified(email_token.user_id)

    async def login(self, email: str, password: str) -> str:
        record = await self._accounts.get_auth_by_email(email.strip().lower())
        if record is None or not self._hasher.verify(password, record.password_hash):
            raise AuthenticationError("invalid email or password")
        if not record.is_verified:
            raise AuthenticationError("account not verified")
        return self._token_service.issue_access_token(str(record.id))

    async def request_reset(self, email: str) -> None:
        # Always succeeds from the caller's view (no account enumeration); only acts if found.
        record = await self._accounts.get_auth_by_email(email.strip().lower())
        if record is None:
            return
        await self._issue_email_token(record.id, record.email, TokenPurpose.RESET)

    async def reset_password(self, token: str, new_password: str) -> None:
        email_token = await self._consume(token, TokenPurpose.RESET)
        await self._accounts.set_password_hash(email_token.user_id, self._hasher.hash(new_password))

    async def _issue_email_token(self, user_id: UUID, email: str, purpose: TokenPurpose) -> None:
        plaintext = secrets.token_urlsafe(32)
        hours = (
            self._settings.verify_token_ttl_h
            if purpose is TokenPurpose.VERIFY
            else self._settings.reset_token_ttl_h
        )
        await self._tokens.create(
            user_id=user_id,
            purpose=purpose,
            token_hash=_hash_token(plaintext),
            expires_at=self._clock.now() + timedelta(hours=hours),
        )
        if purpose is TokenPurpose.VERIFY:
            await self._mailer.send_verification(email, plaintext)
        else:
            await self._mailer.send_reset(email, plaintext)

    async def _consume(self, token: str, purpose: TokenPurpose) -> EmailToken:
        email_token = await self._tokens.get_by_hash(_hash_token(token), purpose)
        if email_token is None:
            raise TokenError("invalid token")
        now = self._clock.now()
        email_token.consume(now)  # raises TokenError if already used or expired
        await self._tokens.mark_consumed(email_token.id, now)
        return email_token
