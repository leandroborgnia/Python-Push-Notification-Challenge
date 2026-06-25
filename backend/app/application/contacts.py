from __future__ import annotations

from uuid import UUID

from app.domain.contacts import Contact, validate_contact_destinations
from app.ports.repositories import ContactRepository


class ContactsService:
    """Add + list a user's private contacts book (FR-008/FR-009). All access is owner-scoped."""

    def __init__(self, contacts: ContactRepository) -> None:
        self._contacts = contacts

    async def add_contact(
        self,
        owner_id: UUID,
        *,
        display_name: str,
        email: str | None,
        phone: str | None,
        device_token: str | None,
    ) -> Contact:
        validate_contact_destinations(email, phone, device_token)
        return await self._contacts.add(
            owner_id=owner_id,
            display_name=display_name,
            email=email,
            phone=phone,
            device_token=device_token,
        )

    async def list_contacts(self, owner_id: UUID, *, limit: int, offset: int) -> list[Contact]:
        return await self._contacts.list_for_owner(owner_id, limit=limit, offset=offset)
