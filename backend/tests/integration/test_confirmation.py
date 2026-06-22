from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.adapters.persistence import models
from app.adapters.persistence.models import Delivery as DeliveryModel
from app.adapters.persistence.models import DeliveryTransition
from app.infra.db.async_engine import get_async_sessionmaker
from tests.conftest import AuthedUser, register_verify_login
from tests.fakes import FakeMailer
from tests.helpers import poll_deliveries

pytestmark = pytest.mark.integration


async def _seed_sent_delivery(
    user_id: UUID, *, provider_ref: str, channel: str = "email", destination: str = "x@example.com"
) -> UUID:
    async with get_async_sessionmaker()() as session:
        dispatch = models.Dispatch(user_id=user_id, channel=channel, title="t", content="c")
        session.add(dispatch)
        await session.flush()
        delivery = models.Delivery(
            dispatch_id=dispatch.id,
            recipient_name="X",
            destination=destination,
            status="sent",
            provider_ref=provider_ref,
        )
        session.add(delivery)
        await session.flush()
        session.add(
            DeliveryTransition(delivery_id=delivery.id, from_status="queued", to_status="sent")
        )
        await session.commit()
        return delivery.id


async def _status_of(delivery_id: UUID) -> tuple[str, str | None]:
    async with get_async_sessionmaker()() as session:
        row = await session.get(DeliveryModel, delivery_id)
        assert row is not None
        return row.status, row.failure_reason


async def test_webhook_marks_delivered(client: AsyncClient, authed_user: AuthedUser) -> None:
    delivery_id = await _seed_sent_delivery(authed_user.user_id, provider_ref="pref-d")
    resp = await client.post(
        "/api/v1/webhooks/delivery",
        json={"provider_ref": "pref-d", "outcome": "delivered"},
    )
    assert resp.status_code == 204
    assert await _status_of(delivery_id) == ("delivered", None)


async def test_webhook_marks_failed_with_reason(
    client: AsyncClient, authed_user: AuthedUser
) -> None:
    delivery_id = await _seed_sent_delivery(authed_user.user_id, provider_ref="pref-f")
    resp = await client.post(
        "/api/v1/webhooks/delivery",
        json={"provider_ref": "pref-f", "outcome": "failed", "reason": "bounced"},
    )
    assert resp.status_code == 204
    assert await _status_of(delivery_id) == ("failed", "bounced")


async def test_duplicate_webhook_is_ignored(client: AsyncClient, authed_user: AuthedUser) -> None:
    delivery_id = await _seed_sent_delivery(authed_user.user_id, provider_ref="pref-dup")
    body = {"provider_ref": "pref-dup", "outcome": "delivered"}
    assert (await client.post("/api/v1/webhooks/delivery", json=body)).status_code == 204
    assert (await client.post("/api/v1/webhooks/delivery", json=body)).status_code == 204

    assert (await _status_of(delivery_id))[0] == "delivered"
    # The terminal transition was recorded exactly once (append-only, never overwritten).
    async with get_async_sessionmaker()() as session:
        delivered_count = await session.scalar(
            select(func.count())
            .select_from(DeliveryTransition)
            .where(
                DeliveryTransition.delivery_id == delivery_id,
                DeliveryTransition.to_status == "delivered",
            )
        )
    assert delivered_count == 1


async def test_uncorrelated_webhook_is_ignored(
    client: AsyncClient, authed_user: AuthedUser
) -> None:
    delivery_id = await _seed_sent_delivery(authed_user.user_id, provider_ref="pref-known")
    resp = await client.post(
        "/api/v1/webhooks/delivery",
        json={"provider_ref": "totally-unknown", "outcome": "delivered"},
    )
    assert resp.status_code == 204  # accepted, but no state change
    assert (await _status_of(delivery_id))[0] == "sent"


async def test_sms_poll_confirms_delivered(
    committing_client: AsyncClient,
    io_worker: None,
    migrated_db: tuple[str, str, str],
    fake_mailer: FakeMailer,
) -> None:
    sync_url = migrated_db[1]
    user = await register_verify_login(
        committing_client, fake_mailer, email="smsuser@example.com", password="passphrase ok"
    )
    contact = await committing_client.post(
        "/api/v1/contacts",
        headers=user.headers,
        json={"display_name": "Sms", "phone": "+15551230000"},
    )
    template = await committing_client.post(
        "/api/v1/templates",
        headers=user.headers,
        json={
            "title": "Code",
            "content": "Your code is 1234",
            "channel": "sms",
            "recipient_contact_ids": [contact.json()["id"]],
        },
    )
    ack = await committing_client.post(
        f"/api/v1/templates/{template.json()['id']}/send", headers=user.headers
    )
    dispatch_id = UUID(ack.json()["dispatch_id"])

    # Real io worker: queued → sent → (poll provider) → delivered.
    snapshot = poll_deliveries(sync_url, dispatch_id, until={"delivered", "failed"})
    assert snapshot, "worker wrote no delivery rows"
    assert all(status == "delivered" for status, _ in snapshot)
