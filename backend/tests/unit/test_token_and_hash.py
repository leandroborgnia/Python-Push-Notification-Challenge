from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.adapters.security.hasher import Argon2PasswordHasher
from app.adapters.security.jwt import PyJwtTokenService
from app.domain.accounts import EmailToken, TokenPurpose
from app.domain.errors import TokenError
from app.ports.clock import FixedClock


def test_argon2_hash_verify_roundtrip() -> None:
    hasher = Argon2PasswordHasher()
    hashed = hasher.hash("correct horse battery")

    assert hashed != "correct horse battery"  # not reversible/plaintext (FR-002)
    assert hasher.verify("correct horse battery", hashed) is True
    assert hasher.verify("wrong password", hashed) is False


_SECRET_A = "test-secret-key-at-least-32-bytes-long!"
_SECRET_B = "another-secret-key-at-least-32-bytes-ok"


def test_jwt_issue_and_decode_roundtrip() -> None:
    clock = FixedClock(datetime(2026, 6, 22, 12, 0, tzinfo=UTC))
    service = PyJwtTokenService(secret=_SECRET_A, algorithm="HS256", access_ttl_min=30, clock=clock)
    subject = str(uuid4())

    token = service.issue_access_token(subject)

    assert service.decode_subject(token) == subject


def test_jwt_expired_token_rejected() -> None:
    clock = FixedClock(datetime(2026, 6, 22, 12, 0, tzinfo=UTC))
    service = PyJwtTokenService(secret=_SECRET_A, algorithm="HS256", access_ttl_min=30, clock=clock)
    token = service.issue_access_token("user")

    clock.advance(seconds=31 * 60)  # advance past the 30-minute TTL

    with pytest.raises(TokenError):
        service.decode_subject(token)


def test_jwt_bad_signature_rejected() -> None:
    clock = FixedClock(datetime(2026, 6, 22, 12, 0, tzinfo=UTC))
    issuer = PyJwtTokenService(secret=_SECRET_A, algorithm="HS256", access_ttl_min=30, clock=clock)
    attacker = PyJwtTokenService(
        secret=_SECRET_B, algorithm="HS256", access_ttl_min=30, clock=clock
    )
    token = issuer.issue_access_token("user")

    with pytest.raises(TokenError):
        attacker.decode_subject(token)


def test_email_token_single_use() -> None:
    now = datetime(2026, 6, 22, 12, 0, tzinfo=UTC)
    token = EmailToken(
        id=uuid4(),
        user_id=uuid4(),
        purpose=TokenPurpose.VERIFY,
        expires_at=now + timedelta(hours=1),
    )

    assert token.is_valid(now) is True
    token.consume(now)
    assert token.consumed_at == now

    with pytest.raises(TokenError):
        token.consume(now)  # already consumed → single-use


def test_email_token_expired_cannot_be_consumed() -> None:
    now = datetime(2026, 6, 22, 12, 0, tzinfo=UTC)
    token = EmailToken(
        id=uuid4(),
        user_id=uuid4(),
        purpose=TokenPurpose.RESET,
        expires_at=now - timedelta(seconds=1),
    )

    assert token.is_valid(now) is False
    with pytest.raises(TokenError):
        token.consume(now)
