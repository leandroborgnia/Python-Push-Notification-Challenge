from __future__ import annotations

import pytest
import respx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.persistence.models import DeliveryTransition
from app.domain.dispatch import DeliveryStatus, FailureReason
from tests.factories import make_delivery, make_dispatch, make_user
from tests.helpers import PROVIDER_BASE_URL, build_delivery_service

pytestmark = pytest.mark.integration


def _to_statuses(session_factory: sessionmaker[Session], delivery_id: object) -> list[str]:
    with session_factory() as session:
        rows = session.execute(
            select(DeliveryTransition.to_status)
            .where(DeliveryTransition.delivery_id == delivery_id)
            .order_by(DeliveryTransition.id)
        )
        return list(rows.scalars().all())


def test_missing_destination_fails_directly(
    sync_session_factory: sessionmaker[Session], truncate_notification_tables: None
) -> None:
    user = make_user(sync_session_factory)
    dispatch = make_dispatch(sync_session_factory, user_id=user.id, channel="email")
    delivery = make_delivery(sync_session_factory, dispatch_id=dispatch.id, destination=None)

    ip = build_delivery_service(sync_session_factory)
    assert ip.service.deliver_one(delivery.id) is DeliveryStatus.FAILED

    saved = ip.deliveries.get(delivery.id)
    assert saved is not None
    assert saved.status is DeliveryStatus.FAILED
    assert saved.failure_reason == FailureReason.MISSING_DESTINATION.value
    # Direct queued→failed: never passed through 'sent' (FR-022).
    assert _to_statuses(sync_session_factory, delivery.id) == ["queued", "failed"]


def test_invalid_email_format_fails(
    sync_session_factory: sessionmaker[Session], truncate_notification_tables: None
) -> None:
    user = make_user(sync_session_factory)
    dispatch = make_dispatch(sync_session_factory, user_id=user.id, channel="email")
    delivery = make_delivery(
        sync_session_factory, dispatch_id=dispatch.id, destination="not-an-email"
    )

    ip = build_delivery_service(sync_session_factory)
    assert ip.service.deliver_one(delivery.id) is DeliveryStatus.FAILED

    saved = ip.deliveries.get(delivery.id)
    assert saved is not None
    assert saved.failure_reason == FailureReason.INVALID_FORMAT.value


def test_invalid_device_token_fails(
    sync_session_factory: sessionmaker[Session], truncate_notification_tables: None
) -> None:
    user = make_user(sync_session_factory)
    dispatch = make_dispatch(sync_session_factory, user_id=user.id, channel="push")
    delivery = make_delivery(sync_session_factory, dispatch_id=dispatch.id, destination="short")

    ip = build_delivery_service(sync_session_factory)
    assert ip.service.deliver_one(delivery.id) is DeliveryStatus.FAILED

    saved = ip.deliveries.get(delivery.id)
    assert saved is not None
    assert saved.failure_reason == FailureReason.INVALID_DEVICE_TOKEN.value


@respx.mock
def test_batch_continues_past_a_failing_recipient(
    sync_session_factory: sessionmaker[Session], truncate_notification_tables: None
) -> None:
    respx.post(f"{PROVIDER_BASE_URL}/send").respond(
        202, json={"provider_ref": "ref-ok", "accepted_at": "2026-06-22T00:00:00Z"}
    )
    user = make_user(sync_session_factory)
    dispatch = make_dispatch(sync_session_factory, user_id=user.id, channel="email")
    failing = make_delivery(sync_session_factory, dispatch_id=dispatch.id, destination=None)
    healthy = make_delivery(
        sync_session_factory, dispatch_id=dispatch.id, destination="ok@example.com"
    )

    ip = build_delivery_service(sync_session_factory)
    assert ip.service.deliver_one(failing.id) is DeliveryStatus.FAILED
    assert ip.service.deliver_one(healthy.id) is DeliveryStatus.SENT  # batch proceeds (FR-022)

    failed = ip.deliveries.get(failing.id)
    sent = ip.deliveries.get(healthy.id)
    assert failed is not None and failed.status is DeliveryStatus.FAILED
    assert sent is not None and sent.status is DeliveryStatus.SENT
    assert sent.provider_ref == "ref-ok"
