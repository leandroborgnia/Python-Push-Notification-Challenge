from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.adapters.persistence.models import Dispatch as DispatchModel
from app.infra.db.async_engine import get_async_sessionmaker
from tests.conftest import AuthedUser, register_verify_login
from tests.fakes import FakeMailer

pytestmark = pytest.mark.integration


async def _add_contact(client: AsyncClient, headers: dict[str, str], **overrides: Any) -> str:
    payload: dict[str, Any] = {"display_name": "Contact", "email": "c@example.com"}
    payload.update(overrides)
    resp = await client.post("/api/v1/contacts", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def test_template_crud_no_send(client: AsyncClient, authed_user: AuthedUser) -> None:
    contact_id = await _add_contact(client, authed_user.headers)

    created = await client.post(
        "/api/v1/templates",
        headers=authed_user.headers,
        json={
            "title": "Welcome",
            "content": "Hi!",
            "channel": "email",
            "recipient_contact_ids": [contact_id],
        },
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]
    assert created.json()["recipient_contact_ids"] == [contact_id]

    listed = await client.get("/api/v1/templates", headers=authed_user.headers)
    assert listed.status_code == 200
    assert [t["id"] for t in listed.json()] == [template_id]

    modified = await client.put(
        f"/api/v1/templates/{template_id}",
        headers=authed_user.headers,
        json={
            "title": "Welcome v2",
            "content": "Hello!",
            "channel": "email",
            "recipient_contact_ids": [contact_id],
        },
    )
    assert modified.status_code == 200
    assert modified.json()["title"] == "Welcome v2"

    deleted = await client.delete(f"/api/v1/templates/{template_id}", headers=authed_user.headers)
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/templates", headers=authed_user.headers)).json() == []

    # No send ever happened during create/modify/delete (FR-017).
    async with get_async_sessionmaker()() as session:
        dispatch_count = await session.scalar(select(func.count()).select_from(DispatchModel))
    assert dispatch_count == 0


async def test_sms_over_160_rejected(client: AsyncClient, authed_user: AuthedUser) -> None:
    contact_id = await _add_contact(client, authed_user.headers, phone="+15551234567")
    resp = await client.post(
        "/api/v1/templates",
        headers=authed_user.headers,
        json={
            "title": "Too long",
            "content": "x" * 161,
            "channel": "sms",
            "recipient_contact_ids": [contact_id],
        },
    )
    assert resp.status_code == 422


async def test_unknown_channel_rejected(client: AsyncClient, authed_user: AuthedUser) -> None:
    contact_id = await _add_contact(client, authed_user.headers)
    resp = await client.post(
        "/api/v1/templates",
        headers=authed_user.headers,
        json={
            "title": "Bad channel",
            "content": "hi",
            "channel": "telegram",
            "recipient_contact_ids": [contact_id],
        },
    )
    assert resp.status_code == 422


async def test_foreign_recipient_rejected(
    client: AsyncClient, fake_mailer: FakeMailer, authed_user: AuthedUser
) -> None:
    user_b = await register_verify_login(
        client, fake_mailer, email="bob@example.com", password="another secret pw"
    )
    foreign_contact = await _add_contact(client, user_b.headers)

    resp = await client.post(
        "/api/v1/templates",
        headers=authed_user.headers,
        json={
            "title": "Steal",
            "content": "hi",
            "channel": "email",
            "recipient_contact_ids": [foreign_contact],
        },
    )
    assert resp.status_code == 422


async def test_cross_user_template_access_404(
    client: AsyncClient, fake_mailer: FakeMailer, authed_user: AuthedUser
) -> None:
    contact_id = await _add_contact(client, authed_user.headers)
    created = await client.post(
        "/api/v1/templates",
        headers=authed_user.headers,
        json={
            "title": "Mine",
            "content": "hi",
            "channel": "email",
            "recipient_contact_ids": [contact_id],
        },
    )
    template_id = created.json()["id"]

    user_b = await register_verify_login(
        client, fake_mailer, email="bob@example.com", password="another secret pw"
    )
    b_contact = await _add_contact(client, user_b.headers)
    put = await client.put(
        f"/api/v1/templates/{template_id}",
        headers=user_b.headers,
        json={
            "title": "hijack",
            "content": "x",
            "channel": "email",
            "recipient_contact_ids": [b_contact],
        },
    )
    assert put.status_code == 404
    assert (
        await client.delete(f"/api/v1/templates/{template_id}", headers=user_b.headers)
    ).status_code == 404
