from __future__ import annotations

from typing import Protocol


class PasswordHasher(Protocol):
    """Hashes and verifies passwords (argon2/bcrypt — never reversible, FR-002)."""

    def hash(self, password: str) -> str: ...

    def verify(self, password: str, hashed: str) -> bool: ...


class TokenService(Protocol):
    """Issues and decodes stateless access tokens (OAuth2 + PyJWT, FR-004)."""

    def issue_access_token(self, subject: str) -> str: ...

    def decode_subject(self, token: str) -> str:
        """Return the token subject. Raises :class:`app.domain.errors.TokenError` if the token is
        missing, malformed, signature-invalid, or expired."""
        ...
