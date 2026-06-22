from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import ContainerDep, CurrentUser
from app.api.schemas import ContactCreate, ContactOut
from app.domain.contacts import Contact

router = APIRouter(prefix="/api/v1/contacts", tags=["contacts"])


def _to_out(contact: Contact) -> ContactOut:
    return ContactOut(
        id=contact.id,
        display_name=contact.display_name,
        email=contact.email,
        phone=contact.phone,
        device_token=contact.device_token,
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ContactOut)
async def add_contact(
    body: ContactCreate, container: ContainerDep, user_id: CurrentUser
) -> ContactOut:
    """Add a contact with at least one destination (FR-008); 422 if none provided."""
    contact = await container.contacts.add_contact(
        user_id,
        display_name=body.display_name,
        email=str(body.email) if body.email else None,
        phone=body.phone,
        device_token=body.device_token,
    )
    return _to_out(contact)


@router.get("", response_model=list[ContactOut])
async def list_contacts(
    container: ContainerDep,
    user_id: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ContactOut]:
    """List only the caller's own contacts (FR-009/FR-010, SC-003)."""
    contacts = await container.contacts.list_contacts(user_id, limit=limit, offset=offset)
    return [_to_out(contact) for contact in contacts]
