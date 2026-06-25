from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

import structlog
from opentelemetry import trace

from app.domain.channels import Channel
from app.domain.dispatch import Delivery, Dispatch, Transition
from app.domain.errors import InvalidSendError, NotFoundError
from app.ports.channels import ChannelPort, ContactSnapshot
from app.ports.repositories import (
    ContactRepository,
    DeliveryRepository,
    DispatchRepository,
    TemplateRepository,
)

_log = structlog.get_logger("app.sending")
_tracer = trace.get_tracer("app.application.sending")


class SendingService:
    """Send a valid template: validate (FR-029), snapshot a Dispatch (FR-030), create one ``queued``
    delivery per recipient, then enqueue background fan-out and return immediately (ack < 1s,
    SC-004). This service never talks to the provider — that happens in the worker."""

    def __init__(
        self,
        *,
        templates: TemplateRepository,
        contacts: ContactRepository,
        dispatches: DispatchRepository,
        deliveries: DeliveryRepository,
        channels: dict[Channel, ChannelPort],
        enqueue: Callable[[UUID], None],
    ) -> None:
        self._templates = templates
        self._contacts = contacts
        self._dispatches = dispatches
        self._deliveries = deliveries
        self._channels = channels
        self._enqueue = enqueue

    async def send_template(self, owner_id: UUID, template_id: UUID) -> UUID:
        template = await self._templates.get_for_owner(owner_id, template_id)
        if template is None:
            raise NotFoundError("template not found")
        if not template.recipient_ids:
            raise InvalidSendError("template has no recipients")
        adapter = self._channels.get(template.channel)
        if adapter is None:
            raise InvalidSendError(f"unsupported channel: {template.channel}")

        contacts = await self._contacts.get_many_for_owner(owner_id, list(template.recipient_ids))
        if not contacts:
            raise InvalidSendError("template has no resolvable recipients")

        with _tracer.start_as_current_span("send.dispatch") as span:
            dispatch = await self._dispatches.create(
                owner_id, channel=template.channel, title=template.title, content=template.content
            )
            for contact in contacts:
                destination = adapter.destination_of(
                    ContactSnapshot(
                        display_name=contact.display_name,
                        email=contact.email,
                        phone=contact.phone,
                        device_token=contact.device_token,
                    )
                )
                await self._deliveries.create_queued(
                    dispatch.id,
                    contact_id=contact.id,
                    recipient_name=contact.display_name,
                    destination=destination,
                )

            span.set_attribute("dispatch.id", str(dispatch.id))
            span.set_attribute("dispatch.channel", template.channel.value)
            span.set_attribute("dispatch.recipients", len(contacts))
            self._enqueue(dispatch.id)  # hand off to the io worker; do not wait for delivery
            _log.info(
                "dispatch_created",
                dispatch_id=str(dispatch.id),
                channel=template.channel.value,
                recipients=len(contacts),
            )
            return dispatch.id


@dataclass(frozen=True, slots=True)
class DeliveryView:
    delivery: Delivery
    transitions: list[Transition]


@dataclass(frozen=True, slots=True)
class DispatchView:
    dispatch: Dispatch
    deliveries: list[DeliveryView]


class SendQueryService:
    """Owner-scoped read model for dispatch status: current per-recipient state + ordered
    transition history (FR-027, SC-006)."""

    def __init__(self, *, dispatches: DispatchRepository, deliveries: DeliveryRepository) -> None:
        self._dispatches = dispatches
        self._deliveries = deliveries

    async def list_for_owner(
        self, owner_id: UUID, *, limit: int, offset: int
    ) -> list[DispatchView]:
        dispatches = await self._dispatches.list_for_owner(owner_id, limit=limit, offset=offset)
        return [await self._view(dispatch) for dispatch in dispatches]

    async def get_for_owner(self, owner_id: UUID, dispatch_id: UUID) -> DispatchView:
        dispatch = await self._dispatches.get_for_owner(owner_id, dispatch_id)
        if dispatch is None:
            raise NotFoundError("dispatch not found")
        return await self._view(dispatch)

    async def _view(self, dispatch: Dispatch) -> DispatchView:
        deliveries = await self._deliveries.list_for_dispatch(dispatch.id)
        views = [
            DeliveryView(
                delivery=delivery,
                transitions=await self._deliveries.transitions_for_delivery(delivery.id),
            )
            for delivery in deliveries
        ]
        return DispatchView(dispatch=dispatch, deliveries=views)
