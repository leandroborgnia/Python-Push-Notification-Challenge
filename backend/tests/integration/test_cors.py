"""CORS enablement (feature 005, FR-040 / contracts/backend-cors.md).

The only backend change in the web-frontend feature is registering ``CORSMiddleware`` so the browser
SPA at ``http://app.localhost`` can call the API at ``http://api.localhost``. These assertions use
the FastAPI test client and need **no** DB or broker: CORS is pure middleware, so the client is
built without entering the lifespan (which is what wires the DB/telemetry container).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import get_settings

ALLOWED_ORIGIN = "http://app.localhost"
DISALLOWED_ORIGIN = "http://evil.example"


def _client() -> TestClient:
    # No ``with`` ⇒ lifespan (DB/telemetry wiring) does not run; settings cache is reset so the
    # default allow-list applies regardless of test ordering.
    get_settings.cache_clear()
    return TestClient(create_app())


def test_preflight_from_allowed_origin_returns_cors_headers() -> None:
    client = _client()
    resp = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert resp.status_code in (200, 204)
    assert resp.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    allow_methods = resp.headers["access-control-allow-methods"]
    assert allow_methods == "*" or "POST" in allow_methods
    allow_headers = resp.headers["access-control-allow-headers"].lower()
    assert "authorization" in allow_headers
    assert "content-type" in allow_headers


def test_actual_request_from_allowed_origin_echoes_origin() -> None:
    client = _client()
    # An unknown path 404s at routing without touching the container; the CORS middleware still
    # decorates the response, which is all this case asserts.
    resp = client.get("/api/v1/__cors_probe__", headers={"Origin": ALLOWED_ORIGIN})

    assert resp.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN


def test_disallowed_origin_gets_no_cors_header() -> None:
    client = _client()
    resp = client.get("/api/v1/__cors_probe__", headers={"Origin": DISALLOWED_ORIGIN})

    assert "access-control-allow-origin" not in resp.headers
