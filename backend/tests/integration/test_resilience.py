from __future__ import annotations

import time

import httpx
import pytest
import respx
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.persistence.models import Delivery as DeliveryModel
from app.domain.dispatch import DeliveryStatus, FailureReason
from tests.factories import make_delivery, make_dispatch, make_user
from tests.helpers import PROVIDER_BASE_URL, build_delivery_service

pytestmark = pytest.mark.integration


def _accepted(provider_ref: str = "ref") -> httpx.Response:
    return httpx.Response(
        202, json={"provider_ref": provider_ref, "accepted_at": "2026-06-22T00:00:00Z"}
    )


def _seed_delivery(
    session_factory: sessionmaker[Session], *, destination: str, channel: str = "email"
) -> DeliveryModel:
    user = make_user(session_factory)
    dispatch = make_dispatch(session_factory, user_id=user.id, channel=channel)
    return make_delivery(session_factory, dispatch_id=dispatch.id, destination=destination)


@respx.mock
def test_retry_then_success(
    sync_session_factory: sessionmaker[Session], truncate_notification_tables: None
) -> None:
    route = respx.post(f"{PROVIDER_BASE_URL}/send").mock(
        side_effect=[httpx.Response(429), httpx.Response(429), _accepted("ref-1")]
    )
    delivery = _seed_delivery(sync_session_factory, destination="a@example.com")

    ip = build_delivery_service(sync_session_factory, max_attempts=3, backoff_base_s=0.0)
    assert ip.service.deliver_one(delivery.id) is DeliveryStatus.SENT

    assert route.call_count == 3  # two 429s retried, third accepted
    saved = ip.deliveries.get(delivery.id)
    assert saved is not None and saved.provider_ref == "ref-1"


@respx.mock
def test_timeout_is_retried(
    sync_session_factory: sessionmaker[Session], truncate_notification_tables: None
) -> None:
    route = respx.post(f"{PROVIDER_BASE_URL}/send").mock(
        side_effect=[httpx.TimeoutException("slow"), _accepted("ref-2")]
    )
    delivery = _seed_delivery(sync_session_factory, destination="b@example.com")

    ip = build_delivery_service(sync_session_factory, max_attempts=3, backoff_base_s=0.0)
    assert ip.service.deliver_one(delivery.id) is DeliveryStatus.SENT
    assert route.call_count == 2


@respx.mock
def test_retries_exhausted_then_failed(
    sync_session_factory: sessionmaker[Session], truncate_notification_tables: None
) -> None:
    route = respx.post(f"{PROVIDER_BASE_URL}/send").respond(429)
    delivery = _seed_delivery(sync_session_factory, destination="c@example.com")

    ip = build_delivery_service(sync_session_factory, max_attempts=3, backoff_base_s=0.0)
    assert ip.service.deliver_one(delivery.id) is DeliveryStatus.FAILED

    assert route.call_count == 3  # stop_after_attempt(3)
    saved = ip.deliveries.get(delivery.id)
    assert saved is not None and saved.failure_reason == FailureReason.CHANNEL_ERROR.value


@respx.mock
def test_breaker_opens_and_short_circuits(
    sync_session_factory: sessionmaker[Session], truncate_notification_tables: None
) -> None:
    route = respx.post(f"{PROVIDER_BASE_URL}/send").respond(429)
    user = make_user(sync_session_factory)
    dispatch = make_dispatch(sync_session_factory, user_id=user.id, channel="email")
    # Same destination → same breaker key.
    deliveries = [
        make_delivery(sync_session_factory, dispatch_id=dispatch.id, destination="rate@example.com")
        for _ in range(3)
    ]

    ip = build_delivery_service(
        sync_session_factory, max_attempts=3, fail_max=5, backoff_base_s=0.0
    )
    results = [ip.service.deliver_one(d.id) for d in deliveries]

    assert all(r is DeliveryStatus.FAILED for r in results)
    assert ip.breakers.get("email:rate@example.com").current_state == "open"
    # d1: 3 calls, d2: 2 calls (trips at the 5th failure), d3: 0 (open → short-circuit).
    assert route.call_count == 5


@respx.mock
def test_idempotency_no_duplicate_send(
    sync_session_factory: sessionmaker[Session], truncate_notification_tables: None
) -> None:
    route = respx.post(f"{PROVIDER_BASE_URL}/send").respond(
        202, json={"provider_ref": "ref-once", "accepted_at": "2026-06-22T00:00:00Z"}
    )
    delivery = _seed_delivery(sync_session_factory, destination="once@example.com")

    ip = build_delivery_service(sync_session_factory, backoff_base_s=0.0)
    assert ip.service.deliver_one(delivery.id) is DeliveryStatus.SENT
    # A redelivery of the same delivery does not send again (status no longer queued).
    assert ip.service.deliver_one(delivery.id) is None
    assert route.call_count == 1


@respx.mock
def test_breaker_half_open_recovery(
    sync_session_factory: sessionmaker[Session], truncate_notification_tables: None
) -> None:
    route = respx.post(f"{PROVIDER_BASE_URL}/send").respond(429)
    user = make_user(sync_session_factory)
    dispatch = make_dispatch(sync_session_factory, user_id=user.id, channel="email")
    seed = [
        make_delivery(sync_session_factory, dispatch_id=dispatch.id, destination="rec@example.com")
        for _ in range(3)
    ]

    ip = build_delivery_service(
        sync_session_factory, max_attempts=1, fail_max=2, reset_timeout=0.5, backoff_base_s=0.0
    )
    ip.service.deliver_one(seed[0].id)
    ip.service.deliver_one(seed[1].id)
    assert ip.breakers.get("email:rec@example.com").current_state == "open"

    time.sleep(0.6)  # let the reset timeout elapse → next call is a half-open trial
    route.mock(return_value=_accepted("ref-recovered"))
    assert ip.service.deliver_one(seed[2].id) is DeliveryStatus.SENT
    assert ip.breakers.get("email:rec@example.com").current_state == "closed"
