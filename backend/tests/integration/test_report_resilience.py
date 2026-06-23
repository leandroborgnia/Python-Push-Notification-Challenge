from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.persistence.sync_repo import (
    SyncDeliveryRepository,
    SyncDispatchReader,
    SyncIdempotencyKeyRepository,
    SyncReportSendRepository,
)
from app.adapters.resilience.breaker import PyBreakerCircuitBreaker
from app.application.delivery import DeliveryService
from app.application.resilience import ResiliencePolicy
from app.domain.channels import Channel
from app.domain.dispatch import DeliveryStatus
from tests.fakes import FailingReportChannel

pytestmark = pytest.mark.integration

_PNG = b"\x89PNG\r\n\x1a\n0"


def _service(
    session_factory: sessionmaker[Session],
    channel: FailingReportChannel,
    *,
    max_attempts: int = 3,
    fail_max: int = 5,
) -> tuple[DeliveryService, PyBreakerCircuitBreaker]:
    breakers = PyBreakerCircuitBreaker(fail_max=fail_max, reset_timeout=30.0)
    resilience = ResiliencePolicy(breakers=breakers, max_attempts=max_attempts, backoff_base_s=0.0)
    service = DeliveryService(
        deliveries=SyncDeliveryRepository(session_factory),
        dispatches=SyncDispatchReader(session_factory),
        idempotency=SyncIdempotencyKeyRepository(session_factory),
        channels={Channel.REPORT: channel},
        resilience=resilience,
    )
    return service, breakers


def test_failing_report_recipient_isolated_others_delivered(
    sync_session_factory: sessionmaker[Session], truncate_notification_tables: None
) -> None:
    sends = SyncReportSendRepository(sync_session_factory)
    bad = sends.create_report_delivery(
        to_email="bad@example.com", subject="Report", body="b", png=_PNG
    )
    good = sends.create_report_delivery(
        to_email="good@example.com", subject="Report", body="b", png=_PNG
    )
    channel = FailingReportChannel(failing={"bad@example.com"})
    service, _ = _service(sync_session_factory, channel)

    # The failing recipient retries then fails (queued -> failed, persisted), the other succeeds —
    # one recipient's failure never blocks the rest (FR-019, SC-003).
    assert service.deliver_one(bad) is DeliveryStatus.FAILED
    assert service.deliver_one(good) is DeliveryStatus.SENT

    assert channel.sent == ["good@example.com"]
    assert channel.calls.count("bad@example.com") == 3  # retry/backoff exhausted (max_attempts)

    deliveries = SyncDeliveryRepository(sync_session_factory)
    failed = deliveries.get(bad)
    assert failed is not None and failed.status is DeliveryStatus.FAILED
    sent = deliveries.get(good)
    assert sent is not None and sent.status is DeliveryStatus.SENT


def test_repeated_report_failures_open_the_breaker(
    sync_session_factory: sessionmaker[Session], truncate_notification_tables: None
) -> None:
    sends = SyncReportSendRepository(sync_session_factory)
    deliveries = [
        sends.create_report_delivery(
            to_email="rate@example.com", subject="Report", body="b", png=_PNG
        )
        for _ in range(3)
    ]
    channel = FailingReportChannel(failing={"rate@example.com"})
    service, breakers = _service(sync_session_factory, channel, max_attempts=1, fail_max=2)

    results = [service.deliver_one(d) for d in deliveries]

    assert all(r is DeliveryStatus.FAILED for r in results)
    # Same destination → same breaker key; it opens and short-circuits the third attempt.
    assert breakers.get("report:rate@example.com").current_state == "open"
    assert len(channel.calls) == 2  # d1, d2 hit the channel; d3 short-circuited by the open breaker
