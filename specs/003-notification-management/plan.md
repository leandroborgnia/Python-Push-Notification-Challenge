# Implementation Plan: Notification Template Management & Multi-Channel Sending

**Branch**: `003-notification-management` | **Date**: 2026-06-22 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/003-notification-management/spec.md`

## Summary

This is the feature that turns the liveness skeleton (001/002) into a working notification service. It
delivers the real domain end-to-end **through the API** (no frontend — out of scope):

- **Auth** — register → email-verify → login (OAuth2 password flow, PyJWT access token) → password
  reset; ownership enforced on every resource. Verification/reset emails go out a **separate, real,
  direct SMTP path** (not the simulated channels).
- **Contacts** — per-user private contacts book (add + list), each with optional email / phone /
  device-token destinations.
- **Templates** — per-user reusable definitions (title, content, single channel, recipient contacts);
  full CRUD; channel-specific validation (SMS ≤ 160 chars at save); creating/editing **never** sends.
- **Sending** — send a valid template; immediate "accepted" ack (< 1 s); background fan-out to each
  recipient on the **`io` (threads) queue**; each recipient is an independent, resilient delivery with
  a persisted, append-only lifecycle `queued → sent → delivered | failed`.
- **Resilience (the core learning goal)** — retry with exponential backoff + jitter (**tenacity**),
  per-channel/destination circuit breaker (**pybreaker**), and **hand-rolled idempotency** keys that
  prevent duplicate delivery on retry.
- **Simulated channels + async confirmation** — `simulatedEmail` / `simulatedSMS` / `simulatedPush`
  call a separate **in-repo simulated-provider HTTP service** that injects failure modes and confirms
  asynchronously: **webhook callback** to us for email/push, **status endpoint we poll** for SMS.

All technology/architecture choices are fixed by the constitution and the spec's Clarifications
(Session 2026-06-21, nine entries). The five plan-level decisions the spec deferred were resolved with
the user on 2026-06-22 and are recorded under [Resolved Plan Decisions](#resolved-plan-decisions) and in
[research.md](./research.md). This plan maps decisions onto concrete structure; it does not re-decide
the inherited stack. **This feature is entirely I/O-bound; the `cpu` (prefork) pool is not exercised**
(the constitution's CPU usage-aggregation task is deferred to a later admin-notification spec).

## Technical Context

**Language/Version**: Python **3.13** (`requires-python = ">=3.13"`, single-version CI). No frontend
work in this feature.

**Primary Dependencies**: FastAPI, uvicorn (uvloop + httptools), SQLAlchemy 2.0, asyncpg (API engine),
psycopg v3 (worker engine), Pydantic v2 + pydantic-settings, Alembic, Celery + RabbitMQ. **New for
003**: `PyJWT` (tokens — constitution mandates PyJWT, never python-jose), `argon2-cffi` (password
hashing), `python-multipart` (OAuth2 password form), `email-validator` (Pydantic `EmailStr`),
`tenacity` (retry/backoff), `pybreaker` (circuit breaker), `aiosmtplib` (auth-email SMTP). Observability
(structlog, OpenTelemetry, sentry-sdk) and tooling (uv, ruff, mypy, pre-commit) unchanged. Tests:
pytest, pytest-asyncio, httpx.AsyncClient, Testcontainers (Postgres **and** RabbitMQ), respx, Coveralls.

**Storage**: PostgreSQL. New Alembic revision (`0002_notification_domain`) adds: `user_account`,
`email_token` (verification/reset), `contact`, `template`, `template_recipient`, `dispatch`,
`delivery`, `delivery_transition` (append-only), `idempotency_key`. Written by the API via the async
engine and by Celery workers via the **sync** engine; ORM models are shared.

**Testing**: pytest + pytest-asyncio. Unit: domain validation + resilience (backoff, breaker
open/half-open/close, idempotent replay) through ports with fakes. Integration: against real Postgres +
RabbitMQ via Testcontainers — auth flow, ownership/cross-user denial, template CRUD, and sending. **A
note on the respx-vs-worker seam** (constitution V mandates *both* respx-mocked channel HTTP *and*
real-worker routing tests — these cannot coexist in one test because respx, an in-process monkeypatch,
cannot intercept HTTP made inside a worker subprocess): the two mandates are satisfied by *different*
tests. **Resilience/failure-mode** tests exercise `application/delivery.py` **in-process** with **respx**
(429/timeout/error injection) — this is where the constitution's respx-mocked boundary lives.
**Routing/round-trip** tests prove Celery fan-out by driving a **real `io` worker** against a **real
in-test `provider_sim`** (a controllable in-repo fake, returning success) — respx is not used there.
Confirmation: the webhook path is tested by POSTing the in-process route directly; the SMS-poll path
runs the real worker + `provider_sim`. SMTP is faked through the mailer port (token asserted via the
persistence port); no real SMTP in tests.

**Test DB isolation** (constitution V): API/in-process tests use **transaction-rollback** isolation (a
shared connection + nested SAVEPOINT per test); rows written by a **worker subprocess** are isolated by
**truncation** (rollback cannot span the worker's own connection).

**Target Platform**: Linux containers. Dev: local **kind** cluster via `scripts/up-dev.sh` /
`up-dev.ps1` at `http://app.localhost` (002). Prod: Kubernetes single-uvicorn pods. Celery `io`
(threads) worker is a separate Deployment; `cpu` (prefork) worker remains from the skeleton but is
unused by this feature. New in-cluster workloads: a **simulated-provider** service and a **Mailpit**
mail catcher (dev).

**Project Type**: Web application (monorepo: `backend/` + `frontend/`); this feature is backend-only.

**Performance Goals** (from Success Criteria): send-request ack **< 1 s** regardless of recipient count
or channel latency (SC-004); onboarding register→template **< 5 min** (SC-001).

**Constraints**: Async all the way in the API — no blocking calls in the event loop; all blocking I/O
(SMTP, channel HTTP) is either awaited via async clients (API path) or offloaded to Celery (send path).
Celery uses the **sync psycopg v3** engine, never asyncpg. Resilience lives in `application/`, never in
adapters (adapters only simulate/forward). Append-only lifecycle — transitions never overwritten.
Webhook endpoints are unauthenticated machine-to-machine and exempt from the user-token rule; integrity
is by delivery correlation + idempotency. Secrets via pydantic-settings/env. Ship the Alembic revision
in this PR. Never edit an applied migration.

**Scale/Scope**: Portfolio scope — ~9 new tables, ~5 API routers (auth/contacts/templates/sends/webhooks),
3 simulated channel adapters behind one `ChannelPort`, 1 simulated-provider service, 3 Celery tasks
(fan-out, deliver, sms-poll). No CPU/analytics work (deferred). No frontend.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| # | Principle | Status | How this plan complies |
|---|-----------|--------|------------------------|
| I | Code Quality (typed, linted, observable, pinned) | ✅ PASS | ruff + mypy (strict) via pre-commit & CI; structlog/OTel/Sentry already wired; config via pydantic-settings (token lifetimes, SMTP, provider URL, resilience knobs — no `os.environ`); new deps version-pinned in `pyproject.toml`/`uv.lock`; images stay multi-stage + pinned (002). |
| II | Architecture (hexagonal, proportionate, open/closed) | ✅ PASS | Pure entities in `domain/` (no FastAPI/SQLAlchemy/Celery); `ChannelPort`, repositories, `PasswordHasher`, `TokenService`, `Mailer`, `CircuitBreaker` are **ports**; all I/O in `adapters/`. **Each channel = one adapter** under `adapters/channels/<name>/`; the shared dispatch/resilience flow has no per-channel branches → adding a channel touches no existing channel (FR-028 / SC-008). |
| III | Background Processing (Celery, mixed workload, sync seam) | ✅ PASS | Channel sends + SMS polling are I/O-bound → **`io` (threads)** queue; workers use the **sync psycopg v3** engine + `sync_repo`, API uses **asyncpg** + `async_repo` (shared models). The `cpu` (prefork) pool exists but is intentionally idle here (CPU task deferred — documented, not removed). |
| IV | Resilience (first-class — the core learning goal) | ✅ PASS | Adapters simulate latency/random errors/429/timeouts (via the provider service); `application/` wraps every send with tenacity backoff + pybreaker per channel/destination + hand-rolled idempotency; lifecycle `queued → sent → delivered \| failed` persisted append-only; all failure modes (backoff, breaker states, idempotent replay) covered by tests. |
| V | Testing (real Postgres + broker, mocked HTTP, non-negotiable) | ✅ PASS | Integration on real Postgres + RabbitMQ (Testcontainers). Both mandates are met by **different** tests (respx can't patch a worker subprocess): **resilience** tests run `application/delivery.py` **in-process with respx** (not adapter internals); the **routing round-trip** drives a **real `io` worker** against a real in-test `provider_sim` (see Technical Context → Testing, research §10). API tests use transaction-rollback; worker-subprocess rows cleaned by truncation; coverage → Coveralls. |
| VI | Security (tokens, hashing, secrets) | ✅ PASS | OAuth2 + **PyJWT** access tokens; **argon2** hashing (argon2-cffi); secrets only via env. Webhook endpoints' user-token exemption is deliberate (machine-to-machine, FR-006) and compensated by correlation + idempotency, not left open to state corruption. |
| VII | Operations (Docker, GH Actions, Kubernetes) | ✅ PASS | Single-uvicorn API pods; separate `io` worker Deployment; new simulated-provider + Mailpit (dev) workloads reuse the multi-stage image (different commands); schema change ships as Alembic `0002` run by the existing migrate Job/init-container (no API-start migration); CI/CD on GitHub Actions. |

**Deliberate stack breadth** (observability, Celery two-pool model, CI/CD) is retained per the
constitution and is **not** logged as complexity. No gate violations → Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/003-notification-management/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions & rationale
├── data-model.md        # Phase 1 — entities, relationships, lifecycle state machine
├── quickstart.md        # Phase 1 — bring-up & per-user-story validation guide
├── contracts/           # Phase 1
│   ├── notification-api.yaml     # OpenAPI: auth, contacts, templates, sends, status, webhooks
│   ├── simulated-provider.yaml   # OpenAPI: the in-repo provider (send, SMS status, callback shape)
│   └── channel-port.md           # Internal ChannelPort contract (the Open/Closed seam)
├── checklists/
│   └── requirements.md  # Spec quality checklist (already passing)
└── tasks.md             # Phase 2 — /speckit-tasks (NOT created here)
```

### Source Code (repository root)

```text
backend/
  app/
    domain/
      accounts.py            # UserAccount, VerificationStatus, EmailToken (purpose=verify|reset) — pure
      contacts.py            # Contact, Destinations (email/phone/device_token) — pure
      templates.py           # Template + channel-specific validation (SMS ≤160) — pure
      channels.py            # Channel enum (EMAIL/SMS/PUSH); destination selection per channel — pure
      dispatch.py            # Dispatch (snapshot), Delivery, DeliveryStatus, FailureReason, Transition — pure
      errors.py              # domain errors (ValidationError, NotFound, Forbidden, InvalidSend…)
    ports/
      repositories.py        # (extend) Account/Contact/Template/Dispatch/Delivery/IdempotencyKey repos
      channels.py            # ChannelPort (strategy); SendResult / ProviderRef
      security.py            # PasswordHasher, TokenService (issue/verify JWT)
      mailer.py              # Mailer (auth verification/reset emails)
      clock.py               # Clock (now()) — token expiry & poll windows, testable
    application/
      accounts.py            # register, verify_email, login, request_reset, reset_password
      contacts.py            # add_contact, list_contacts
      templates.py           # create/modify/delete/list (ownership + validation)
      sending.py             # send_template: validate, snapshot dispatch, fan-out enqueue (returns ack)
      delivery.py            # deliver_one: idempotency + breaker + retry → ChannelPort.send → transitions
      confirmation.py        # apply_confirmation (webhook), poll_sms_status (bounded), correlation
      resilience.py          # backoff policy (tenacity), breaker registry (pybreaker), idempotency guard
    adapters/
      channels/
        email/__init__.py    # SimulatedEmailChannel (ChannelPort) — validates email, HTTP→provider
        sms/__init__.py      # SimulatedSmsChannel  (ChannelPort) — HTTP→provider, poll-confirmed
        push/__init__.py     # SimulatedPushChannel (ChannelPort) — validates device token, HTTP→provider
        provider_http.py     # shared async/sync HTTP client to the simulated provider (respx-mockable)
      persistence/
        models.py            # (extend) ORM for the 9 new tables (shared by both engines)
        async_repo.py        # (extend) AsyncSession repos — API path
        sync_repo.py         # (extend) sync Session repos — Celery path
      security/
        hasher.py            # Argon2PasswordHasher (argon2-cffi)
        jwt.py               # PyJwtTokenService (HS256, settings-driven lifetime)
      mailer/
        smtp.py              # SmtpMailer (aiosmtplib) — auth emails only
      resilience/
        breaker.py           # PyBreakerCircuitBreaker (per channel/destination registry)
    infra/
      db/async_engine.py     # (reuse)
      db/sync_engine.py      # (reuse)
      telemetry.py           # (reuse)
    api/
      deps.py                # (extend) container wiring + current_user (Bearer) dependency
      schemas.py             # (extend) Pydantic DTOs (auth/contacts/templates/sends/status/webhooks)
      routers/
        auth.py              # register, verify, login (token), reset-request, reset-confirm
        contacts.py          # add, list
        templates.py         # create, modify, delete, list
        sends.py             # POST send; GET send activity / per-recipient status
        webhooks.py          # POST delivery confirmation (email/push) — unauthenticated, correlated
    tasks/
      celery_app.py          # (extend include list)
      sending.py             # dispatch_fanout (io) → deliver(io) per recipient; sms_poll(io) re-enqueue
    provider_sim/
      main.py                # separate FastAPI app (app.provider_sim.main:app): accept send, inject
                             #   failures, schedule webhook callback (email/push), serve SMS status
    bootstrap.py             # (extend) bind new ports → adapters
    main.py                  # (reuse) mount new routers
    settings.py              # (extend) token lifetimes, SMTP, provider base URL, resilience knobs
  migrations/versions/
    0002_notification_domain.py   # all 9 tables + constraints/indexes
  tests/
    unit/                    # domain validation; resilience (backoff/breaker/idempotency); lifecycle
    integration/
      test_auth_flow.py      # register→verify→login→reset; gating; gating-before-verify
      test_contacts.py       # add/list; cross-user denial
      test_templates.py      # CRUD; SMS≤160; recipient-ownership; no-send-on-edit
      test_sending.py        # ack<1s; fan-out; real io worker; respx provider; repeated sends
      test_confirmation.py   # webhook delivered/failed; SMS poll; idempotent/uncorrelated callbacks
      test_resilience.py     # respx 429/timeout → backoff; breaker open/half-open; no duplicate
      test_validation_fail.py# missing-destination/invalid-format → queued→failed(reason)
    factories/               # user/contact/template/dispatch/delivery factories
    conftest.py              # (extend) auth client fixture, io-worker fixture, respx provider fixture
  pyproject.toml             # (extend) new runtime deps
frontend/                    # unchanged (UI out of scope)
deploy/k8s/
  base/                      # (extend) io-worker already present; add provider-sim Deployment+Service
  overlays/dev/              # add Mailpit Deployment+Service; provider-sim env; SMTP→mailpit
  overlays/prod/             # provider-sim wired; (real SMTP/provider would replace sims later)
```

**Structure Decision**: Web-application hexagonal layout per CLAUDE.md, dependencies pointing inward to
`domain/`. New domain rules → `domain/`; orchestration + resilience → `application/`; all framework/I/O →
`adapters/` (channels, persistence, security, mailer, resilience) and `infra/`; HTTP surface → `api/`;
background entrypoints → `tasks/` (thin, delegate to `application/`). The Open/Closed channel seam is a
single `ChannelPort` with one adapter per channel under `adapters/channels/<name>/`; the dispatch and
resilience code in `application/` is channel-agnostic. The simulated provider is an independent FastAPI
app (`app/provider_sim/`) so it is a real network peer in kind yet fully replaceable by respx in tests.

## Resolved Plan Decisions

The spec deferred these to planning; resolved with the user 2026-06-22 (details + alternatives in
[research.md](./research.md)).

1. **Simulated providers** — a separate in-repo **simulated-provider HTTP service** (own Deployment in
   kind, same image/different command). Channel adapters call it over HTTP. It injects failure modes and
   drives confirmation. In tests: **respx** for in-process resilience tests, a **real `provider_sim`** for
   the real-worker routing round-trip (respx can't patch a worker subprocess — see Technical Context →
   Testing and research §10).
2. **Confirmation drivers** — **SMS**: a Celery `io` task polls the provider status endpoint on a
   bounded re-enqueue schedule. **Email/Push**: an unauthenticated FastAPI **webhook route** records the
   provider's callback. Both correlate by the delivery's provider reference and are idempotent.
3. **Resilience build-vs-buy** — **tenacity** (retry/backoff + jitter) and **pybreaker** (per
   channel/destination circuit breaker); **idempotency hand-rolled** (persisted key + unique
   constraint). Lives in `application/`, framework-free, unit-tested through ports.
4. **Auth-email path** — `aiosmtplib` `Mailer` adapter behind a port; dev points at an in-cluster
   **Mailpit** catcher (mail really sent + viewable); tests use a fake mailer and assert the token via
   the persistence port.
5. **Tuning defaults** — access token **30 min**; verify token **24 h**; reset token **1 h**; retry
   **3 attempts**, backoff base **0.5 s** ×2 + jitter; breaker opens at **5** consecutive
   failures/destination, half-open after **30 s**; SMS poll every **3 s** up to **~30 s** then stop
   (leave `sent`). All in `settings.py`, overridable via env.

## Complexity Tracking

> No Constitution Check violations. The broad stack and the extra dev workloads (simulated provider,
> Mailpit) are deliberate, test/dev doubles for the simulated-channel design — not added product
> complexity. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |

## Phase Outputs

- **Phase 0** → [research.md](./research.md): auth (argon2/PyJWT/OAuth2 password flow + lifetimes),
  auth-email (aiosmtplib + Mailpit + token-via-port testing), simulated-provider service + respx
  boundary, confirmation (SMS poll task vs email/push webhook) with correlation/idempotency, resilience
  (tenacity + pybreaker + hand-rolled idempotency), lifecycle persistence, API conventions, tuning
  defaults — each with rationale + alternatives.
- **Phase 1** → [data-model.md](./data-model.md), [contracts/](./contracts/),
  [quickstart.md](./quickstart.md); agent context (`CLAUDE.md` SPECKIT marker) updated to this plan.
- **Phase 2** → `/speckit-tasks` will generate `tasks.md` (not produced by this command).
```