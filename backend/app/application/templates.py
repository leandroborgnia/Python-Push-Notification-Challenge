from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from app.domain.errors import NotFoundError
from app.domain.templates import (
    Template,
    ensure_recipients_owned,
    parse_channel,
    validate_sms_length,
)
from app.ports.repositories import ContactRepository, TemplateRepository


class TemplatesService:
    """Per-user template CRUD with channel-specific validation. Creating/editing NEVER sends
    (FR-017); ownership and recipient-ownership are enforced (FR-011)."""

    def __init__(self, templates: TemplateRepository, contacts: ContactRepository) -> None:
        self._templates = templates
        self._contacts = contacts

    async def create(
        self,
        owner_id: UUID,
        *,
        title: str,
        content: str,
        channel: str,
        recipient_ids: Sequence[UUID],
    ) -> Template:
        parsed = parse_channel(channel)
        validate_sms_length(parsed, content)
        await self._ensure_recipients_owned(owner_id, recipient_ids)
        return await self._templates.create(
            owner_id,
            title=title,
            content=content,
            channel=parsed,
            recipient_ids=list(recipient_ids),
        )

    async def modify(
        self,
        owner_id: UUID,
        template_id: UUID,
        *,
        title: str,
        content: str,
        channel: str,
        recipient_ids: Sequence[UUID],
    ) -> Template:
        parsed = parse_channel(channel)
        validate_sms_length(parsed, content)
        await self._ensure_recipients_owned(owner_id, recipient_ids)
        updated = await self._templates.update(
            owner_id,
            template_id,
            title=title,
            content=content,
            channel=parsed,
            recipient_ids=list(recipient_ids),
        )
        if updated is None:
            raise NotFoundError("template not found")
        return updated

    async def delete(self, owner_id: UUID, template_id: UUID) -> None:
        if not await self._templates.delete(owner_id, template_id):
            raise NotFoundError("template not found")

    async def list(self, owner_id: UUID, *, limit: int, offset: int) -> list[Template]:
        return await self._templates.list_for_owner(owner_id, limit=limit, offset=offset)

    async def _ensure_recipients_owned(self, owner_id: UUID, recipient_ids: Sequence[UUID]) -> None:
        owned = await self._contacts.owned_ids(owner_id, list(recipient_ids))
        ensure_recipients_owned(recipient_ids, owned)
