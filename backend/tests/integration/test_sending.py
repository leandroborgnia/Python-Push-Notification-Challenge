from __future__ import annotations

import time
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.adapters.persistence.models import Delivery as DeliveryModel
from app.infra.db.async_engine import get_async_sessionmaker
from tests.conftest import AuthedUser, register_verify_login
from tests.fakes import FakeMailer
from tests.helpers import poll_deliveries

pytestmark = pytest.mark.integration


async def _make_template(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    channel: str = "email",
    recipients: int = 1,
) -> str:
    contact_ids: list[str] = []
    for i in range(recipients):
        payload: dict[str, Any] = {"display_name": f"R{i}"}
        payload["phone" if channel == "sms" else "email"] = (
            f"+1555000{i:04d}" if channel == "sms" else f"r{i}@example.com"
        )
        resp = await client.post("/api/v1/contacts", headers=headers, json=payload)
        assert resp.status_code == 201, resp.text
        contact_ids.append(resp.json()["id"])
    resp = await client.post(
        "/api/v1/templates",
        headers=headers,
        json={
            "title": "Welcome",
            "content": "Hello!",
            "channel": channel,
            "recipient_contact_ids": contact_ids,
        },
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def test_send_returns_202_under_1s(
    client: AsyncClient, authed_user: AuthedUser, enqueue_calls: list[UUID]
) -> None:
    template_id = await _make_template(client, authed_user.headers, recipients=3)

    started = time.perf_counter()
    resp = await client.post(f"/api/v1/templates/{template_id}/send", headers=authed_user.headers)
    elapsed = time.perf_counter() - started

    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "accepted"
    assert elapsed < 1.0  # ack does not wait for delivery (SC-004)
    assert UUID(resp.json()["dispatch_id"]) in enqueue_calls  # fan-out was handed off


async def test_fanout_creates_one_queued_delivery_per_recipient(
    client: AsyncClient, authed_user: AuthedUser
) -> None:
    template_id = await _make_template(client, authed_user.headers, recipients=3)
    resp = await client.post(f"/api/v1/templates/{template_id}/send", headers=authed_user.headers)
    dispatch_id = UUID(resp.json()["dispatch_id"])

    async with get_async_sessionmaker()() as session:
        rows = (
            (
                await session.execute(
                    select(DeliveryModel).where(DeliveryModel.dispatch_id == dispatch_id)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 3
    assert all(row.status == "queued" for row in rows)


async def test_resend_creates_a_distinct_dispatch(
    client: AsyncClient, authed_user: AuthedUser
) -> None:
    template_id = await _make_template(client, authed_user.headers)
    first = await client.post(f"/api/v1/templates/{template_id}/send", headers=authed_user.headers)
    second = await client.post(f"/api/v1/templates/{template_id}/send", headers=authed_user.headers)
    assert first.json()["dispatch_id"] != second.json()["dispatch_id"]  # FR-026


async def test_send_without_recipients_400(client: AsyncClient, authed_user: AuthedUser) -> None:
    created = await client.post(
        "/api/v1/templates",
        headers=authed_user.headers,
        json={
            "title": "Empty",
            "content": "hi",
            "channel": "email",
            "recipient_contact_ids": [],
        },
    )
    template_id = created.json()["id"]
    resp = await client.post(f"/api/v1/templates/{template_id}/send", headers=authed_user.headers)
    assert resp.status_code == 400  # invalid to send (FR-029)


async def test_send_unowned_template_404(client: AsyncClient, authed_user: AuthedUser) -> None:
    from uuid import uuid4

    resp = await client.post(f"/api/v1/templates/{uuid4()}/send", headers=authed_user.headers)
    assert resp.status_code == 404


async def test_real_worker_drives_queued_to_sent(
    committing_client: AsyncClient,
    io_worker: None,
    migrated_db: tuple[str, str, str],
    fake_mailer: FakeMailer,
) -> None:
    sync_url = migrated_db[1]
    user = await register_verify_login(
        committing_client, fake_mailer, email="sender@example.com", password="passphrase ok"
    )
    template_id = await _make_template(committing_client, user.headers, channel="email")

    ack = await committing_client.post(
        f"/api/v1/templates/{template_id}/send", headers=user.headers
    )
    assert ack.status_code == 202
    dispatch_id = UUID(ack.json()["dispatch_id"])

    # A real io worker consumes from RabbitMQ and sends against the real in-test provider_sim.
    snapshot = poll_deliveries(sync_url, dispatch_id, until={"sent", "delivered", "failed"})
    assert snapshot, "worker wrote no delivery rows"
    assert all(status == "sent" for status, _ in snapshot)
    assert all(provider_ref for _, provider_ref in snapshot)
