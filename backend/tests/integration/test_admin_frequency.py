from __future__ import annotations

import pytest

from tests.conftest import AdminContext, register_verify_login

pytestmark = pytest.mark.integration

_FREQ = "/api/v1/admin/stats-report/frequency"


async def test_get_returns_provisioned_default(admin_client: AdminContext) -> None:
    resp = await admin_client.client.get(_FREQ, headers=admin_client.admin.headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"interval_seconds": 2_592_000, "enabled": True}


async def test_post_valid_interval_persists(admin_client: AdminContext) -> None:
    headers = admin_client.admin.headers
    resp = await admin_client.client.post(_FREQ, headers=headers, json={"interval_seconds": 86_400})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"interval_seconds": 86_400, "enabled": True}

    # Persisted: a fresh GET reflects the new value.
    again = await admin_client.client.get(_FREQ, headers=headers)
    assert again.json() == {"interval_seconds": 86_400, "enabled": True}


async def test_post_below_minimum_rejected_and_unchanged(admin_client: AdminContext) -> None:
    headers = admin_client.admin.headers
    await admin_client.client.post(_FREQ, headers=headers, json={"interval_seconds": 86_400})

    resp = await admin_client.client.post(_FREQ, headers=headers, json={"interval_seconds": 3_600})
    assert resp.status_code == 422, resp.text

    # Stored value unchanged (SC-002).
    again = await admin_client.client.get(_FREQ, headers=headers)
    assert again.json() == {"interval_seconds": 86_400, "enabled": True}


async def test_post_zero_disables(admin_client: AdminContext) -> None:
    headers = admin_client.admin.headers
    resp = await admin_client.client.post(_FREQ, headers=headers, json={"interval_seconds": 0})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"interval_seconds": 0, "enabled": False}


async def test_non_admin_forbidden_on_get_and_post(admin_client: AdminContext) -> None:
    user = await register_verify_login(
        admin_client.client,
        admin_client.fake_mailer,
        email="ordinary@example.com",
        password="not an admin pw",
    )
    get_resp = await admin_client.client.get(_FREQ, headers=user.headers)
    assert get_resp.status_code == 403, get_resp.text

    post_resp = await admin_client.client.post(
        _FREQ, headers=user.headers, json={"interval_seconds": 86_400}
    )
    assert post_resp.status_code == 403, post_resp.text


async def test_missing_token_unauthenticated(admin_client: AdminContext) -> None:
    assert (await admin_client.client.get(_FREQ)).status_code == 401


async def test_invalid_token_unauthenticated(admin_client: AdminContext) -> None:
    bad = {"Authorization": "Bearer not-a-real-token"}
    assert (await admin_client.client.get(_FREQ, headers=bad)).status_code == 401
