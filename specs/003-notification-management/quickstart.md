# Quickstart & Validation: Notification Template Management & Multi-Channel Sending

A run/validation guide proving the feature end-to-end **through the API** (no UI — out of scope).
Implementation detail lives in `tasks.md` (Phase 2) and the code; this file is how you *exercise* it.

## Prerequisites

- The 002 dev stack (kind + `app.localhost`). Bring it up:
  - Windows: `./up-dev.ps1`  ·  Linux/WSL: `scripts/up-dev.sh`
- `003` adds two dev workloads to the cluster: a **simulated-provider** Deployment and a **Mailpit**
  mail catcher (Service + web UI). They come up with the stack.
- Schema: the `migrate-<tag>` Job applies Alembic `0002_notification_domain`; the API init-container
  waits for head before serving.
- Base URL: `http://api.localhost/api/v1`. Mailpit UI: `http://mail.localhost` (dev overlay).

> Run `pytest` on the **host** (Testcontainers needs the Docker daemon), never inside a pod.

## Local one-offs (host)

```bash
cd backend
uv sync
uv run alembic upgrade head                 # against a local/devc Postgres
uv run uvicorn app.main:app --reload --port 8000
uv run celery -A app.tasks.celery_app worker --pool=threads -n io@%h -Q io -c 20
uv run uvicorn app.provider_sim.main:app --port 9000   # the simulated provider (dev only)
```

## Story 1 — Secure account access (P1)

```bash
# Register (201, unverified) → verification email lands in Mailpit
curl -sX POST api.localhost/api/v1/auth/register -H 'content-type: application/json' \
  -d '{"email":"ada@example.com","password":"correct horse"}'
# Pre-verify login is refused
curl -sX POST api.localhost/api/v1/auth/login -d 'username=ada@example.com&password=correct horse'   # 400
# Grab the verify token from Mailpit UI (dev), then:
curl -sX POST 'api.localhost/api/v1/auth/verify?token=<TOKEN>'                                        # 200
# Login → access token
TOKEN=$(curl -sX POST api.localhost/api/v1/auth/login \
  -d 'username=ada@example.com&password=correct horse' | jq -r .access_token)
# Protected call works with token, 401 without
curl -s api.localhost/api/v1/contacts -H "authorization: Bearer $TOKEN"     # 200
curl -s api.localhost/api/v1/contacts                                        # 401
```
**Expected**: unverified→no token; verified→token; token gates protected endpoints; reset flow
(`/auth/reset-request` → token from Mailpit → `/auth/reset-confirm`) invalidates the old password.

## Story 4 — Contacts book (P2)

```bash
curl -sX POST api.localhost/api/v1/contacts -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"display_name":"Grace","email":"grace@example.com","phone":"+15551234567","device_token":"dev-abc"}'
curl -s api.localhost/api/v1/contacts -H "authorization: Bearer $TOKEN"
```
**Expected**: contact stored & listed for the owner only; a second user cannot see/use it (404).

## Story 2 — Manage templates (P1)

```bash
# Create (no send). Use the contact id from above.
curl -sX POST api.localhost/api/v1/templates -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"title":"Welcome","content":"Hi!","channel":"email","recipient_contact_ids":["<CID>"]}'
# SMS >160 chars → 422
# Referencing another user's contact → 422
```
**Expected**: create/modify/delete/list work; no send ever occurs; SMS>160 and foreign-contact refs are
rejected at save.

## Story 3 — Send across the channel (P1)

```bash
# Immediate accept (<1s), background delivery
curl -sX POST api.localhost/api/v1/templates/<TID>/send -H "authorization: Bearer $TOKEN"   # 202 {dispatch_id}
# Watch per-recipient lifecycle + transitions
curl -s api.localhost/api/v1/sends/<DISPATCH_ID> -H "authorization: Bearer $TOKEN"
```
**Expected**:
- 202 in < 1 s regardless of recipients/latency (SC-004).
- Each delivery: `queued → sent` (provider accept) → `delivered|failed` once the **provider confirms**
  (email/push via webhook to `/webhooks/delivery`; SMS via the poll task).
- A recipient missing the channel destination → `queued → failed (missing_destination)`; the rest still
  send (FR-022).
- Re-send the same template → a **new** independent dispatch (FR-026).
- Under simulated 429/timeout/errors the delivery retries with backoff, the breaker guards repeats, and
  no recipient is delivered twice (SC-007). A delivery whose confirmation never arrives stays `sent`.

## Test suite (host)

```bash
cd backend
uv run pytest                                   # full suite (Testcontainers Postgres + RabbitMQ)
uv run pytest tests/integration/test_sending.py # send round-trip w/ real io worker + respx provider
uv run pytest tests/integration/test_resilience.py::test_retry_then_breaker_no_duplicate
uv run ruff check . && uv run ruff format --check . && uv run mypy .
```

**Validation mapping**: `test_auth_flow`→US1/SC-001-002; `test_contacts`+`test_templates`→US2/US4/SC-003;
`test_sending`+`test_confirmation`→US3/SC-004-006; `test_resilience`→SC-007;
channel-registry test→SC-008; `test_validation_fail`→FR-022/SC-009. respx mocks the provider HTTP; the
mailer is faked and the verify/reset token is asserted via the persistence port.
