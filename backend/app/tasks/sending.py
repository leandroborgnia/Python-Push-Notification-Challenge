from __future__ import annotations

from uuid import UUID

from app.domain.channels import Channel
from app.domain.dispatch import DeliveryStatus
from app.ports.channels import ConfirmationMode
from app.tasks.celery_app import celery_app
from app.tasks.deps import get_worker_container

_IO_QUEUE = "io"


@celery_app.task(name="app.tasks.sending.dispatch_fanout")
def dispatch_fanout(dispatch_id: str) -> None:
    """Fan a dispatch out to one ``deliver`` task per queued recipient (io queue)."""
    container = get_worker_container()
    dispatch = container.dispatches.get(UUID(dispatch_id))
    if dispatch is None:
        return
    for delivery_id in container.deliveries.queued_ids_for_dispatch(UUID(dispatch_id)):
        deliver.apply_async(args=[str(delivery_id), dispatch.channel.value], queue=_IO_QUEUE)


@celery_app.task(name="app.tasks.sending.deliver")
def deliver(delivery_id: str, channel: str) -> None:
    """Deliver one recipient resiliently; for POLL channels, kick off SMS status polling."""
    container = get_worker_container()
    status = container.delivery.deliver_one(UUID(delivery_id))
    if (
        status is DeliveryStatus.SENT
        and container.channels[Channel(channel)].confirmation_mode() is ConfirmationMode.POLL
    ):
        sms_poll.apply_async(
            args=[delivery_id, 0.0],
            queue=_IO_QUEUE,
            countdown=container.settings.sms_poll_interval_s,
        )


@celery_app.task(name="app.tasks.sending.sms_poll")
def sms_poll(delivery_id: str, elapsed: float = 0.0) -> None:
    """Poll the provider for an SMS outcome; self re-enqueue with countdown until the window
    elapses, then stop (leaving the delivery ``sent`` — no auto-fail, research §5)."""
    container = get_worker_container()
    if container.sms_poll.poll_once(UUID(delivery_id)):
        return
    interval = container.settings.sms_poll_interval_s
    next_elapsed = elapsed + interval
    if next_elapsed <= container.settings.sms_poll_window_s:
        sms_poll.apply_async(args=[delivery_id, next_elapsed], queue=_IO_QUEUE, countdown=interval)
