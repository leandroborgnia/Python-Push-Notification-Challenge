from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.adapters.persistence.models import EmailToken as EmailTokenModel
from app.infra.db.async_engine import get_async_sessionmaker
from tests.conftest import AuthedUser
from tests.fakes import FakeMailer

pytestmark = pytest.mark.integration


async def test_register_201_and_duplicate_409(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register", json={"email": "ada@example.com", "password": "correct horse"}
    )
    assert resp.status_code == 201

    # Case-insensitive duplicate is rejected (FR-001).
    dup = await client.post(
        "/api/v1/auth/register", json={"email": "ADA@example.com", "password": "another secret"}
    )
    assert dup.status_code == 409


async def test_login_refused_before_verify_then_succeeds(
    client: AsyncClient, fake_mailer: FakeMailer
) -> None:
    email, password = "grace@example.com", "passphrase ok"
    assert (
        await client.post("/api/v1/auth/register", json={"email": email, "password": password})
    ).status_code == 201

    pre = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert pre.status_code == 400  # unverified (FR-003/FR-004)

    token = fake_mailer.verification_token_for(email)
    assert (await client.post("/api/v1/auth/verify", params={"token": token})).status_code == 200

    ok = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert ok.status_code == 200
    assert ok.json()["access_token"]


async def test_verify_is_single_use(client: AsyncClient, fake_mailer: FakeMailer) -> None:
    email = "single@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "passphrase ok"})
    token = fake_mailer.verification_token_for(email)

    assert (await client.post("/api/v1/auth/verify", params={"token": token})).status_code == 200
    assert (await client.post("/api/v1/auth/verify", params={"token": token})).status_code == 400


async def test_verify_expired_token_rejected(client: AsyncClient, fake_mailer: FakeMailer) -> None:
    email = "expired@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "passphrase ok"})
    token = fake_mailer.verification_token_for(email)

    # Expire the token in-place via the same bound, in-transaction session.
    async with get_async_sessionmaker()() as session:
        await session.execute(
            update(EmailTokenModel).values(expires_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await session.commit()

    assert (await client.post("/api/v1/auth/verify", params={"token": token})).status_code == 400


async def test_protected_endpoint_token_gated(client: AsyncClient, authed_user: AuthedUser) -> None:
    with_token = await client.get("/api/v1/auth/me", headers=authed_user.headers)
    assert with_token.status_code == 200
    assert with_token.json()["user_id"] == str(authed_user.user_id)

    assert (await client.get("/api/v1/auth/me")).status_code == 401
    bad = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nonsense"})
    assert bad.status_code == 401


async def test_password_reset_invalidates_old_password(
    client: AsyncClient, fake_mailer: FakeMailer
) -> None:
    email, old_pw, new_pw = "reset@example.com", "old passphrase", "new passphrase!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": old_pw})
    await client.post(
        "/api/v1/auth/verify", params={"token": fake_mailer.verification_token_for(email)}
    )
    assert (
        await client.post("/api/v1/auth/login", data={"username": email, "password": old_pw})
    ).status_code == 200

    assert (
        await client.post("/api/v1/auth/reset-request", json={"email": email})
    ).status_code == 202
    reset_token = fake_mailer.reset_token_for(email)
    assert (
        await client.post(
            "/api/v1/auth/reset-confirm",
            json={"token": reset_token, "new_password": new_pw},
        )
    ).status_code == 200

    old = await client.post("/api/v1/auth/login", data={"username": email, "password": old_pw})
    assert old.status_code == 400  # old password no longer works (FR-005)
    new = await client.post("/api/v1/auth/login", data={"username": email, "password": new_pw})
    assert new.status_code == 200
