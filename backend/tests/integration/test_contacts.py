from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import AuthedUser, register_verify_login
from tests.fakes import FakeMailer

pytestmark = pytest.mark.integration


async def test_add_contact_with_destination_201(
    client: AsyncClient, authed_user: AuthedUser
) -> None:
    resp = await client.post(
        "/api/v1/contacts",
        headers=authed_user.headers,
        json={"display_name": "Grace", "email": "grace@example.com"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"]
    assert body["display_name"] == "Grace"
    assert body["email"] == "grace@example.com"


async def test_add_contact_without_destination_422(
    client: AsyncClient, authed_user: AuthedUser
) -> None:
    resp = await client.post(
        "/api/v1/contacts", headers=authed_user.headers, json={"display_name": "No Dest"}
    )
    assert resp.status_code == 422, resp.text


async def test_list_returns_only_own_contacts(
    client: AsyncClient, fake_mailer: FakeMailer, authed_user: AuthedUser
) -> None:
    await client.post(
        "/api/v1/contacts",
        headers=authed_user.headers,
        json={"display_name": "Grace", "phone": "+15551234567"},
    )
    own = await client.get("/api/v1/contacts", headers=authed_user.headers)
    assert own.status_code == 200
    assert [c["display_name"] for c in own.json()] == ["Grace"]

    # A second user sees none of the first user's contacts (privacy boundary, SC-003).
    user_b = await register_verify_login(
        client, fake_mailer, email="bob@example.com", password="another secret pw"
    )
    other = await client.get("/api/v1/contacts", headers=user_b.headers)
    assert other.status_code == 200
    assert other.json() == []


async def test_contacts_endpoints_require_auth(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/contacts")).status_code == 401
    create = await client.post(
        "/api/v1/contacts", json={"display_name": "x", "email": "x@example.com"}
    )
    assert create.status_code == 401
