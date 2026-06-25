# Contract: Backend CORS Enablement (the one backend change)

This is the **only** backend modification in this feature (spec Clarifications, FR-040). It adds
cross-origin support so the browser SPA at `http://app.localhost` can call the API at
`http://api.localhost`. No business endpoint, schema, or notification/resilience behavior changes.

## Settings (`backend/app/settings.py`)

Add a config-driven, env-overridable allow-list (Principle I/VI — no hard-coding, no `*`):

```python
# CORS — origins permitted to call the API from a browser (the SPA). Env-overridable; never "*".
cors_allow_origins: list[str] = ["http://app.localhost"]
```

- Dev default: `["http://app.localhost"]`.
- Other environments override via env (e.g. `CORS_ALLOW_ORIGINS=["https://app.example.com"]`), wired
  through the same `pydantic-settings` mechanism as existing settings; pydantic parses the JSON list.
- The dev deploy passes the value through the existing secret/config path used by the API deployment.

## Middleware (`backend/app/main.py`)

Register Starlette's bundled middleware in `create_app()` (no new dependency):

```python
from fastapi.middleware.cors import CORSMiddleware
from app.settings import get_settings

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allow_origins,
    allow_credentials=False,                       # Bearer header, not cookies
    allow_methods=["*"],                           # GET/POST/PUT/DELETE/OPTIONS
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)
```

Rationale for `allow_credentials=False`: the SPA authenticates with an `Authorization: Bearer` header,
not cookies, so credentialed CORS is unnecessary — and it keeps the explicit-origin allow-list valid
(a `*` origin with credentials is forbidden by the spec and by browsers).

## Behavioral contract

- **Preflight** `OPTIONS /api/v1/<any>` with `Origin: http://app.localhost` and
  `Access-Control-Request-Method: POST` ⇒ `200/204` with:
  - `Access-Control-Allow-Origin: http://app.localhost`
  - `Access-Control-Allow-Methods` including the requested method
  - `Access-Control-Allow-Headers` including `authorization, content-type`
- **Actual request** from an allowed origin ⇒ response carries
  `Access-Control-Allow-Origin: http://app.localhost`.
- **Disallowed origin** ⇒ no `Access-Control-Allow-Origin` header (browser blocks; server logic
  unchanged).
- All existing status codes, bodies, and auth behavior are **unchanged** — CORS only adds response
  headers and answers preflights.

## Acceptance (Principle V)

A `pytest` using the FastAPI test client (no DB/broker needed):

1. `OPTIONS` a representative path (e.g. `/api/v1/auth/login`) with the allowed `Origin` and a
   requested method/headers ⇒ assert the three `Access-Control-Allow-*` headers above.
2. A normal request with the allowed `Origin` ⇒ assert `Access-Control-Allow-Origin` echoes it.
3. A request with a disallowed `Origin` ⇒ assert no `Access-Control-Allow-Origin` header.

No Alembic migration (settings/middleware only). Ships in the same PR as the frontend per the repo's
"model change ships with its migration" discipline (here: config change ships with its test).
