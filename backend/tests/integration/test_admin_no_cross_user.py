from __future__ import annotations

import pytest

from tests.conftest import AdminContext
from tests.factories import make_contact, make_delivery, make_dispatch, make_template, make_user

pytestmark = pytest.mark.integration


def _seed_other_users_resources() -> tuple[str, str]:
    """Seed a second ordinary user with a contact + template + a send (committed via factories).

    Returns ``(template_id, dispatch_id)``. Uses the already-configured sync sessionmaker directly
    (not the ``sync_session_factory`` fixture, which would reset the bound async engine)."""
    from app.infra.db.sync_engine import get_sync_sessionmaker

    factory = get_sync_sessionmaker()
    other = make_user(factory, email="other-owner@example.com")
    contact = make_contact(factory, owner_id=other.id)
    template = make_template(factory, owner_id=other.id, recipient_ids=(contact.id,))
    dispatch = make_dispatch(factory, user_id=other.id)
    make_delivery(factory, dispatch_id=dispatch.id)
    return str(template.id), str(dispatch.id)


async def test_admin_has_no_cross_user_access(admin_client: AdminContext) -> None:
    template_id, dispatch_id = _seed_other_users_resources()
    headers = admin_client.admin.headers
    client = admin_client.client

    # The admin is treated as a non-owner: owner-scoped lookups 404 (FR-004), never leak the data.
    body = {"title": "x", "content": "y", "channel": "email", "recipient_contact_ids": []}
    assert (
        await client.put(f"/api/v1/templates/{template_id}", headers=headers, json=body)
    ).status_code == 404
    assert (
        await client.delete(f"/api/v1/templates/{template_id}", headers=headers)
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/templates/{template_id}/send", headers=headers)
    ).status_code == 404
    assert (await client.get(f"/api/v1/sends/{dispatch_id}", headers=headers)).status_code == 404

    # And nothing belonging to the other user appears in the admin's own listings.
    assert (await client.get("/api/v1/contacts", headers=headers)).json() == []
    assert (await client.get("/api/v1/templates", headers=headers)).json() == []
    assert (await client.get("/api/v1/sends", headers=headers)).json() == []
