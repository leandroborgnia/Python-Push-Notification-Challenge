---
description: "Task list for feature 003-notification-management implementation"
---

# Tasks: Notification Template Management & Multi-Channel Sending

**Input**: Design documents from `specs/003-notification-management/`
**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: NON-NEGOTIABLE (constitution Principle V). This feature touches the API, persistence, and
channel sends, so test tasks are **required**, not optional: `pytest` + `pytest-asyncio` via
`httpx.AsyncClient`, integration tests against real Postgres + RabbitMQ (Testcontainers, no DB mocking).
**respx-vs-worker seam**: respx is an in-process monkeypatch and CANNOT intercept HTTP made inside a
worker subprocess, so the constitution's two mandates are split across tests — **resilience/failure-mode**
tests run `application/delivery.py` **in-process with respx** (429/timeout/error injection); the
**routing round-trip** test drives a **real `io` worker against a real in-test `provider_sim`** (success
path) to prove fan-out. **Isolation**: API/in-process tests use transaction-rollback (shared connection +
nested SAVEPOINT); worker-subprocess rows use truncation. The mailer is faked and the verify/reset token
asserted via the persistence port (no real SMTP). Write tests first; ensure they fail before implementing.

**Build order** (confirmed 2026-06-22): **US1 (auth) → US4 (contacts) → US2 (templates) → US3
(sending)** — dependency order, not strict spec priority. US4/US2/US3 need auth; US2 needs contacts;
US3 needs templates. Each story stays independently *testable* via factories.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 / US2 / US3 / US4 (Setup / Foundational / Polish carry no story label)

## Path Conventions

Monorepo hexagonal layout under `backend/app/` (`domain/ ports/ application/ adapters/ infra/ api/
tasks/ provider_sim/`), tests under `backend/tests/`, ops under `deploy/k8s/`. Frontend untouched.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Dependencies, configuration, and shared domain primitives every story needs.

- [X] T001 Add runtime deps to `backend/pyproject.toml` — `PyJWT`, `argon2-cffi`, `python-multipart`, `email-validator`, `tenacity`, `pybreaker`, `aiosmtplib` — then `uv sync` to refresh `backend/uv.lock` (pin per Principle I; mypy override for `pybreaker`/`aiosmtplib` if untyped)
- [X] T002 [P] Extend `backend/app/settings.py` with new settings: `jwt_secret` (a clearly-non-prod **dev/test placeholder** default so dev/test can sign tokens, plus a **fail-fast guard when `environment != "dev"`** and the secret is unset/placeholder — no real secret committed, per Principle VI), `jwt_alg="HS256"`, `access_token_ttl_min=30`, `verify_token_ttl_h=24`, `reset_token_ttl_h=1`; `smtp_host/smtp_port/mail_from`; `provider_base_url`; resilience knobs `retry_max_attempts=3`, `retry_backoff_base_s=0.5`, `breaker_fail_max=5`, `breaker_reset_timeout_s=30`, `sms_poll_interval_s=3`, `sms_poll_window_s=30` (all env-overridable; no `os.environ` reads elsewhere)
- [X] T003 [P] Create `backend/app/domain/errors.py` — `DomainError` base + `ValidationError`, `NotFoundError`, `ForbiddenError`, `InvalidSendError`, `ChannelValidationError`, `TransientChannelError`, `PermanentChannelError`
- [X] T004 [P] Create `backend/app/domain/channels.py` — `Channel` enum (`EMAIL`/`SMS`/`PUSH`) with string values matching the DB `CHECK` (`email`/`sms`/`push`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The shared schema (all tables in one Alembic revision per data-model.md), the clock port,
and the test scaffolding every story's tests rely on.

**⚠️ CRITICAL**: No user-story phase can complete until this phase is done.

- [X] T005 Add ORM models for all 9 tables to `backend/app/adapters/persistence/models.py` (shared by both engines): `user_account`, `email_token`, `contact`, `template`, `template_recipient`, `dispatch`, `delivery`, `delivery_transition`, `idempotency_key` — with PKs/FKs/indexes, `CHECK`s (channel enum, status enum, SMS length, email_token purpose), and uniques: **email via a functional unique index `lower(email)`** on a `text` column (app normalizes to lowercase — no `citext` extension, so `Base.metadata.create_all` works in tests) + unique idempotency key, per [data-model.md](./data-model.md)
- [X] T006 Create Alembic revision `backend/migrations/versions/0002_notification_domain.py` covering all tables/constraints from T005; verify `alembic upgrade head` and `downgrade` against a scratch Postgres (depends on T005; never edit an applied migration)
- [X] T007 [P] Create `backend/app/ports/clock.py` — `Clock` protocol (`now() -> datetime`) + `SystemClock` for prod and a fixed clock usable in tests (token expiry + poll windows)
- [X] T008 [P] Extend `backend/tests/conftest.py` — add an unauthenticated `httpx.AsyncClient` fixture bound to `create_app()`; establish **transaction-rollback isolation** for API/in-process tests (shared connection + nested SAVEPOINT per test, constitution V), reserving **truncation** for worker-subprocess-written rows; keep the existing engine/session reset (depends on T005)
- [X] T009 [P] Create entity factories in `backend/tests/factories/` (user, email_token, contact, template, dispatch, delivery) writing via the sync session — so each story's tests can fabricate cross-story data without the other story's endpoints (depends on T005)

**Checkpoint**: Schema migrates; `Base.metadata.create_all` + factories work; test client boots.

---

## Phase 3: User Story 1 - Secure account access (Priority: P1) 🎯 MVP

**Goal**: register → email-verify → login (PyJWT access token) → password reset; every protected
endpoint is token-gated; ownership scaffolding (`current_user`) exists for later stories.

**Independent Test**: Register → pre-verify login refused → verify → login (token) → call a protected
endpoint with/without the token (200/401) → reset password and confirm the old one no longer works.

### Tests for User Story 1 (write first, must fail)

- [X] T010 [P] [US1] Integration test `backend/tests/integration/test_auth_flow.py` — register(201)/duplicate(409); login-before-verify refused; verify (single-use, expired→400); login→token; protected call 200 with token / 401 without/expired; reset-request→reset-confirm invalidates old password (fake mailer; token read via the email_token repo)
- [X] T011 [P] [US1] Unit test `backend/tests/unit/test_token_and_hash.py` — argon2 hash/verify round-trip; JWT issue/verify/`exp` rejection; `EmailToken` single-use + expiry logic (uses the fixed clock)

### Implementation for User Story 1

- [X] T012 [P] [US1] Create `backend/app/domain/accounts.py` — `UserAccount` (id, email, is_verified), `EmailToken` (purpose verify/reset, expiry, `consume`) — pure, no frameworks
- [X] T013 [P] [US1] Create `backend/app/ports/security.py` — `PasswordHasher` and `TokenService` protocols
- [X] T014 [P] [US1] Create `backend/app/ports/mailer.py` — `Mailer` protocol (`send_verification`, `send_reset`)
- [X] T015 [P] [US1] Create `backend/app/adapters/security/hasher.py` — `Argon2PasswordHasher` (argon2-cffi)
- [X] T016 [P] [US1] Create `backend/app/adapters/security/jwt.py` — `PyJwtTokenService` (HS256, settings TTL, `sub`/`iat`/`exp`)
- [X] T017 [P] [US1] Create `backend/app/adapters/mailer/smtp.py` — `SmtpMailer` (aiosmtplib, settings-driven; awaited from the request path, never via Celery)
- [X] T018 [US1] Add `AccountRepository` + `EmailTokenRepository` protocols to `backend/app/ports/repositories.py`
- [X] T019 [US1] Add `AsyncAccountRepository` + `AsyncEmailTokenRepository` to `backend/app/adapters/persistence/async_repo.py`
- [X] T020 [US1] Create `backend/app/application/accounts.py` — `register`, `verify_email`, `login` (issue token, verified-only), `request_reset`, `reset_password` (depends on T012–T019)
- [X] T021 [US1] Add auth DTOs to `backend/app/api/schemas.py` — `RegisterRequest`, `TokenResponse`, reset-request/confirm DTOs (`EmailStr`)
- [X] T022 [US1] Add the `current_user` Bearer dependency + accounts container wiring to `backend/app/api/deps.py` (401 on missing/invalid/expired)
- [X] T023 [US1] Create `backend/app/api/routers/auth.py` — `POST /api/v1/auth/{register,verify,login,reset-request,reset-confirm}` per [contracts/notification-api.yaml](./contracts/notification-api.yaml)
- [X] T024 [US1] Bind account ports→adapters in `backend/app/bootstrap.py` and mount the auth router in `backend/app/main.py` (`create_app`)
- [X] T025 [US1] Add an `authed_user` fixture to `backend/tests/conftest.py` (register+verify+login helper, fake `Mailer` binding, token-via-repo) for reuse by later stories (depends on T023)
- [X] T026 [P] [US1] Add a Mailpit Deployment+Service to `deploy/k8s/overlays/dev/` and SMTP/JWT keys to `deploy/k8s/overlays/dev/secret.env.example`; wire `SMTP_HOST`→mailpit in the dev overlay (dev-only auth-mail viewing)

**Checkpoint**: US1 fully functional & independently testable — auth + token gating ready for all stories.

---

## Phase 4: User Story 4 - Manage a personal contacts book (Priority: P2)

**Goal**: authenticated users add + list private contacts (name + optional email/phone/device_token),
the recipient source templates will reference.

**Independent Test**: add a contact, list it back, and confirm another user can neither see nor use it.

### Tests for User Story 4 (write first, must fail)

- [X] T027 [P] [US4] Integration test `backend/tests/integration/test_contacts.py` — add (201) with ≥1 destination; add with no destination → 422; list returns only own contacts; user B GET/use of user A's contact → 404 (depends on `authed_user` fixture)

### Implementation for User Story 4

- [X] T028 [P] [US4] Create `backend/app/domain/contacts.py` — `Contact` (owner, display_name, optional destinations) + "≥1 destination" rule — pure
- [X] T029 [US4] Add `ContactRepository` protocol to `backend/app/ports/repositories.py`
- [X] T030 [US4] Add `AsyncContactRepository` (owner-scoped queries) to `backend/app/adapters/persistence/async_repo.py`
- [X] T031 [US4] Create `backend/app/application/contacts.py` — `add_contact`, `list_contacts` (owner-scoped)
- [X] T032 [US4] Add `ContactCreate`/`Contact` DTOs to `backend/app/api/schemas.py`
- [X] T033 [US4] Create `backend/app/api/routers/contacts.py` — `POST /api/v1/contacts`, `GET /api/v1/contacts` (offset/limit), token-gated
- [X] T034 [US4] Wire contacts in `backend/app/bootstrap.py` + `backend/app/api/deps.py`; mount the router in `main.py`

**Checkpoint**: US1 + US4 work independently; contacts available as template recipients.

---

## Phase 5: User Story 2 - Manage notification templates (Priority: P1)

**Goal**: per-user template CRUD (title, content, single channel, recipient contacts); channel-specific
validation (SMS ≤160 at save); recipient contacts must be owned; create/edit never sends.

**Independent Test**: create a template referencing owned contacts, list/modify/list/delete it with no
send occurring; SMS>160 and foreign-contact references are rejected; list shows only own templates.

### Tests for User Story 2 (write first, must fail)

- [X] T035 [P] [US2] Integration test `backend/tests/integration/test_templates.py` — create/modify/delete/list; SMS>160 → 422; channel not in {email,sms,push} → 422; recipient not owned → 422; no send on create/modify; cross-user template access → 404 (uses contact factory)
- [X] T036 [P] [US2] Unit test `backend/tests/unit/test_template_validation.py` — SMS ≤160 rule, channel validation, recipient-ownership rule (pure/domain)

### Implementation for User Story 2

- [X] T037 [P] [US2] Create `backend/app/domain/templates.py` — `Template` entity + channel-specific validation (SMS length; channel ∈ enum) — pure
- [X] T038 [US2] Add `TemplateRepository` protocol (with recipient association) to `backend/app/ports/repositories.py`
- [X] T039 [US2] Add `AsyncTemplateRepository` (+ `template_recipient` writes, owner + recipient-ownership checks) to `backend/app/adapters/persistence/async_repo.py`
- [X] T040 [US2] Create `backend/app/application/templates.py` — `create/modify/delete/list` (ownership + recipient-ownership + validation; never sends)
- [X] T041 [US2] Add `TemplateCreate`/`Template` DTOs to `backend/app/api/schemas.py`
- [X] T042 [US2] Create `backend/app/api/routers/templates.py` — `POST /templates`, `GET /templates` (offset/limit), `PUT /templates/{id}`, `DELETE /templates/{id}` (token-gated; 404 on foreign)
- [X] T043 [US2] Wire templates in `backend/app/bootstrap.py` + `deps.py`; mount the router in `main.py`

**Checkpoint**: US1 + US4 + US2 work; a managed template library exists, still no sending.

---

## Phase 6: User Story 3 - Send a notification across its channel (Priority: P1)

**Goal**: send a valid template; immediate accept (<1s); background fan-out on the `io` queue; per
recipient resilient delivery (`queued → sent → delivered | failed`) with retry/backoff + circuit breaker
+ idempotency; async confirmation (poll for SMS, webhook for email/push); repeatable, snapshot-decoupled.

**Independent Test**: send a valid template → 202 ack <1s → each recipient progresses through its
lifecycle to an outcome via the provider's confirmation; re-send → a separate dispatch; under simulated
429/timeout no recipient is delivered twice; a missing-destination recipient fails while others proceed.

### Tests for User Story 3 (write first, must fail)

- [X] T044 [P] [US3] Integration test `backend/tests/integration/test_sending.py` — `POST /templates/{id}/send` returns 202 `<1s` (SC-004); fan-out creates one `queued` delivery per recipient; a **real `io` worker** drives `queued→sent` against the **real in-test `provider_sim`** (success path; NOT respx — respx can't patch the subprocess); re-send → distinct dispatch; invalid send (no recipients/unsupported channel) → 400
- [X] T045 [P] [US3] Integration test `backend/tests/integration/test_confirmation.py` — email/push: POST the in-process `/webhooks/delivery` route directly → `delivered`/`failed`; SMS: real `io` worker + `provider_sim` poll → `delivered`/`failed`; duplicate + uncorrelated callbacks ignored (no overwrite); no confirmation → stays `sent`
- [X] T046 [P] [US3] Integration test `backend/tests/integration/test_resilience.py` — **in-process** (call `application/delivery.py` directly, no worker subprocess) with **respx** injecting 429/timeout → retry with backoff; breaker opens after `breaker_fail_max`; idempotency → no duplicate delivery; breaker half-open recovery (SC-007)
- [X] T047 [P] [US3] Integration test `backend/tests/integration/test_validation_fail.py` — missing destination / invalid email format / invalid device token → `queued→failed(reason)` directly (never `sent`), batch continues (FR-022, SC-009)
- [X] T048 [P] [US3] Unit test `backend/tests/unit/test_resilience_unit.py` — backoff policy, breaker registry state machine, idempotency guard (through fakes, no broker)
- [X] T049 [P] [US3] Unit test `backend/tests/unit/test_lifecycle.py` — delivery state-machine transitions incl. direct `queued→failed`; append-only transitions never overwritten

### Implementation for User Story 3

- [X] T050 [P] [US3] Create `backend/app/domain/dispatch.py` — `Dispatch` (snapshot), `Delivery`, `DeliveryStatus`, `FailureReason`, `Transition` + transition rules (pure, append-only semantics)
- [X] T051 [P] [US3] Create `backend/app/ports/channels.py` — `ChannelPort`, `ConfirmationMode` (WEBHOOK/POLL), `SendResult`/`ProviderRef`/`PollOutcome` per [contracts/channel-port.md](./contracts/channel-port.md)
- [X] T052 [US3] Add `DispatchRepository`, `DeliveryRepository`, `IdempotencyKeyRepository` protocols (async + sync) to `backend/app/ports/repositories.py`
- [X] T053 [US3] Add async repos (API status reads + webhook write) to `async_repo.py` and **sync** repos (worker writes deliveries/transitions/idempotency) to `backend/app/adapters/persistence/sync_repo.py`
- [X] T054 [P] [US3] Create `backend/app/adapters/channels/provider_http.py` — sync `httpx.Client` to the provider (`/send`, `/sms/{ref}/status`), respx-mockable; raises `TransientChannelError` on 429/timeout/5xx
- [X] T055 [P] [US3] Create `backend/app/adapters/channels/email/__init__.py` — `SimulatedEmailChannel` (validate email format; POST `/send`; mode WEBHOOK)
- [X] T056 [P] [US3] Create `backend/app/adapters/channels/sms/__init__.py` — `SimulatedSmsChannel` (POST `/send`; mode POLL; `poll_status`)
- [X] T057 [P] [US3] Create `backend/app/adapters/channels/push/__init__.py` — `SimulatedPushChannel` (validate device token; POST `/send`; mode WEBHOOK)
- [X] T058 [P] [US3] Create `backend/app/adapters/resilience/breaker.py` — `PyBreakerCircuitBreaker` registry keyed per channel/destination (thread-safe; structlog/OTel listeners on state change)
- [X] T059 [US3] Create `backend/app/application/resilience.py` — tenacity backoff policy + breaker integration + hand-rolled idempotency guard (claim key before send) (depends on T058)
- [X] T060 [US3] Create `backend/app/application/sending.py` — `send_template` (validate FR-029; snapshot `Dispatch`; create `queued` deliveries; enqueue fan-out; return ack) (depends on T050, T052, T053)
- [X] T061 [US3] Create `backend/app/application/delivery.py` — `deliver_one` (pre-send validation → direct `queued→failed`; else idempotency claim → breaker+retry → `ChannelPort.send` → record `sent`; append transitions) (depends on T051, T059)
- [X] T062 [US3] Create `backend/app/application/confirmation.py` — `apply_confirmation` (webhook) + `poll_sms_status` (bounded window) + correlation/idempotency (depends on T053)
- [X] T063 [US3] Create `backend/app/tasks/sending.py` — Celery `io` tasks: `dispatch_fanout` → per-recipient `deliver`; `sms_poll` (self re-enqueue with countdown up to the window) — thin, delegate to `application/` using the **sync** engine
- [X] T064 [US3] Register `app.tasks.sending` in `backend/app/tasks/celery_app.py` `include` list
- [X] T065 [US3] Add send/status/webhook DTOs to `backend/app/api/schemas.py` — `DispatchAck`, `DispatchStatus`, `DeliveryStatus`, `WebhookConfirmation`
- [X] T066 [US3] Create `backend/app/api/routers/sends.py` — `POST /templates/{id}/send` (202), `GET /sends` (offset/limit), `GET /sends/{dispatch_id}` (owner-scoped, 404 on foreign)
- [X] T067 [US3] Create `backend/app/api/routers/webhooks.py` — `POST /api/v1/webhooks/delivery` (UNAUTHENTICATED; correlate by `provider_ref`; idempotent; 204 even for duplicate/uncorrelated)
- [X] T068 [US3] Bind the channel registry (email/sms/push) + dispatch/delivery/confirmation ports in `backend/app/bootstrap.py`; mount sends + webhooks routers in `main.py`
- [X] T069 [P] [US3] Create `backend/app/provider_sim/main.py` — separate FastAPI app: `POST /send` (inject latency/random error/429/timeout, return `provider_ref`), `GET /sms/{ref}/status`, and a delayed callback to the app's `/webhooks/delivery` for email/push
- [X] T070 [US3] Add to `backend/tests/conftest.py`: (a) an `io_worker` fixture (io-only subprocess, env points `PROVIDER_BASE_URL` at the test provider), (b) a **real in-test `provider_sim`** fixture (run `app.provider_sim.main:app` on a real port reachable by the worker subprocess — for the routing round-trip), and (c) a `respx` fixture for **in-process** delivery/resilience tests; worker-written rows cleaned by truncation (depends on T008, T069)
- [X] T071 [P] [US3] Add `provider-sim` Deployment+Service to `deploy/k8s/base/` (same image, command `uvicorn app.provider_sim.main:app`), reference it in `base/kustomization.yaml`, and set `PROVIDER_BASE_URL` in both overlays + `secret.env.example`

**Checkpoint**: All four stories work; resilient, channel-specific, async-confirmed sending is live.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T072 [P] Add structlog fields + OpenTelemetry spans/metrics for send/deliver/confirmation and breaker state changes across `application/` + `tasks/` (reuse `infra/telemetry.py`)
- [X] T073 [P] Add an Open/Closed guard test `backend/tests/unit/test_channel_registry.py` — registry resolves all channels and the dispatcher imports no concrete channel module (SC-008)
- [X] T074 [P] Update `README.md` with the 003 overview (auth, channels, resilience: tenacity + pybreaker + hand-rolled idempotency; simulated provider + webhook/poll confirmation) **and verify/add the constitution-mandated content** (Principle III): the Celery-vs-ARQ/TaskIQ rationale and the single-uvicorn prod process model
- [X] T075 Run `uv run ruff check --fix . && uv run ruff format . && uv run mypy .` (backend) and fix all findings
- [X] T076 Run the full suite `uv run pytest` (Testcontainers Postgres + RabbitMQ + real io worker + respx) and confirm coverage publishes to Coveralls via CI
- [X] T077 Execute [quickstart.md](./quickstart.md) scenarios on the kind dev cluster (US1–US3 end-to-end, Mailpit + provider-sim) and record results. **Validated live** on `kind` v0.32.0 (Docker 28.5.1, WSL): clean `scripts/up-dev.sh` brings all 6 Deployments + Mailpit + provider-sim to Ready; `/health` 200 (data_store/message_broker/cpu+io pools green). **26/26 quickstart checks pass** end-to-end via `curl` against `http://api.localhost/api/v1`: **US1** register 201 / duplicate 409 / pre-verify login 400 / verify-token-from-Mailpit → verify 200 → login 200 (access token) / protected 200-with / 401-without / reset-request → reset-token-from-Mailpit → reset-confirm 200 → old-password 400, new-password 200. **US4** add 201, no-destination 422, owner-scoped list. **US2** create 201, SMS>160 422, foreign-contact 422, bad-channel 422, no send on create. **US3** send **202 in ~0.02s** (SC-004), email delivery **queued→sent→delivered via webhook**, SMS delivery **delivered via poll**, re-send → distinct dispatch. **Two defects found & fixed during validation**: (1) `httpx` was a *dev-only* dep but is imported by runtime code (`adapters/channels/provider_http.py`, pulled into the API via `bootstrap.py`, and `provider_sim`) → prod image crashed `ModuleNotFoundError: httpx`; moved it to `[project.dependencies]` (`uv.lock` refreshed). (2) provider-sim `callback_delay_s=0` let the email webhook race the worker's `record_sent` commit (uncorrelated `provider_ref` → dropped → delivery stranded at `sent`); set `PROVIDER_SIM_CALLBACK_DELAY_S=2` in `deploy/k8s/base/provider-sim.yaml` to model real post-accept latency. Also corrected the quickstart base URL `app.localhost`→`api.localhost` (app.localhost is the frontend; the API ingress host is api.localhost). Host suite green (81 passed) after the dep move.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)**: no dependencies — start immediately.
- **Foundational (P2)**: depends on Setup — **blocks all stories** (schema + factories + client).
- **US1 (P3)**: depends on Foundational. **Prerequisite for US4/US2/US3** (auth + `current_user` + `authed_user` fixture).
- **US4 (P4)**: depends on US1.
- **US2 (P5)**: depends on US1 (auth); uses contact factory (so not hard-blocked by US4, but US4 lands first in delivery order).
- **US3 (P6)**: depends on US2 (templates) + US1.
- **Polish (P7)**: depends on all stories complete.

### Within each story

- Tests first (must fail) → domain → ports → adapters → application → API/tasks → wiring.
- Shared-file edits (`ports/repositories.py`, `api/schemas.py`, `bootstrap.py`, `api/deps.py`, `main.py`, `async_repo.py`, `conftest.py`) are **not** `[P]` within a story — they serialize on the file.

### Parallel opportunities

- Setup: T002/T003/T004 in parallel.
- Foundational: T007/T008/T009 in parallel (after T005/T006).
- Each story's test tasks ([P]) in parallel; new-file creations ([P]) in parallel.
- US3 channel adapters T055/T056/T057 and provider-sim T069 in parallel.

---

## Parallel Example: User Story 1

```bash
# Tests first (parallel):
Task: "Integration test backend/tests/integration/test_auth_flow.py"
Task: "Unit test backend/tests/unit/test_token_and_hash.py"

# New-file implementation (parallel):
Task: "domain/accounts.py"  Task: "ports/security.py"  Task: "ports/mailer.py"
Task: "adapters/security/hasher.py"  Task: "adapters/security/jwt.py"  Task: "adapters/mailer/smtp.py"
```

---

## Implementation Strategy

### MVP first (User Story 1)

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 US1 → **STOP & validate** auth end-to-end →
demo (register/verify/login/reset + token gating).

### Incremental delivery

US1 (auth) → US4 (contacts) → US2 (templates) → US3 (sending). Each phase is an independently testable,
demoable increment; the quickstart can be run cumulatively as each lands.

### Notes

- `[P]` = different files, no incomplete dependency. `[Story]` maps to spec user stories for traceability.
- Celery tasks stay thin and use the **sync psycopg v3** engine (never asyncpg); resilience lives in
  `application/`, never in the channel adapters.
- Ship the Alembic revision in this PR with the model change. Never edit an applied migration.
- Commit after each task or logical group; stop at any checkpoint to validate a story independently.
