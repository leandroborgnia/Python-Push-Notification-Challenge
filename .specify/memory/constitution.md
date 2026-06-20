<!--
SYNC IMPACT REPORT
Version change: 1.1.0 → 1.2.0  (amendment 2026-06-20)
Bump rationale (1.2.0): Principle V (Testing) extended — Testcontainers now MUST cover BOTH PostgreSQL
and RabbitMQ; background-task routing tests run against a real broker with real workers (no mocks, no
eager mode). MINOR: materially expands the testing approach. Triggered by the 001-system-liveness plan
(real broker→worker smoke check).
Version change (prior): 1.0.0 → 1.1.0  (amendment 2026-06-19)
Bump rationale (1.1.0): Principle III refined — the I/O-bound Celery pool is corrected from gevent to
threads (psycopg v3 is natively thread-safe, so no psycogreen monkey-patching is needed; gevent +
psycogreen is documented as the higher-concurrency alternative), and the synchronous driver is pinned
explicitly to psycopg v3 (psycopg3). MINOR: the mixed-workload two-pool design is unchanged; this
refines the prescribed I/O executor and clarifies the driver version. Triggered by the
001-system-liveness spec clarification (Session 2026-06-19).
Bump rationale (1.0.0): First adoption of the constitution; establishes the baseline principle set.

Added principles:
  - I.   Code Quality (Typed, Linted, Observable)
  - II.  Architecture (Hexagonal, Proportionate, Open for Extension)
  - III. Background Processing (Celery, Mixed Workload, Sync Seam)
  - IV.  Resilience (First-Class — The Core Learning Goal)
  - V.   Testing (Real Postgres, Mocked HTTP, Non-Negotiable)
  - VI.  Security (Tokens, Hashing, Secrets)
  - VII. Operations (Docker, GitHub Actions, One Process Model per Environment)

Added sections:
  - Technology Stack (Authoritative & Non-Negotiable)
  - Development Workflow & Quality Gates

Removed sections: none (initial ratification)

Templates reviewed for consistency:
  ✅ .specify/templates/plan-template.md  — Constitution Check gate reads the constitution
       dynamically; the Web-application structure (backend/ + frontend/) is already present.
       No edit required.
  ✅ .specify/templates/spec-template.md  — No new mandatory spec sections introduced.
       No edit required.
  ✅ .specify/templates/tasks-template.md — UPDATED: the authoritative "Tests" note no longer
       calls tests OPTIONAL; testing is NON-NEGOTIABLE per Principle V.

Deferred / follow-up TODOs:
  - README.md does not yet exist. During implementation it MUST document (a) the Celery-vs-
    ARQ/TaskIQ rationale required by Principle III and (b) the chosen prod process model.
  - The exact "bar height" metric of the CPU-bound usage-aggregation task is still open and is
    to be finalized in the relevant spec/plan (Principle III names the task; the metric is TBD).

Ratification date: 2026-06-19 (new project; adopted today).
-->

# Notification Management Service Constitution

This Constitution governs an async FastAPI notification-management service (Email, SMS, Push)
with a React frontend. It is a deliberately broad portfolio/learning project: the stack is
chosen to demonstrate senior-level engineering, and that breadth is intentional. Implementations
MUST be clean and proportionate, but the full stack defined here MUST be retained.

## Core Principles

### I. Code Quality (Typed, Linted, Observable)

- `ruff` (lint + format) and `mypy` MUST both pass with zero errors. They are wired via
  pre-commit and re-verified in CI; code that fails either is not mergeable.
- Python and its dependencies MUST be managed with `uv` (packaging and Python-version pinning);
  the lockfile MUST be committed so environments are reproducible.
- Domain and application code MUST be fully type-annotated; `mypy` MUST run strict enough that
  untyped definitions in those layers fail the check.
- Application code MUST log through `structlog` (no bare `print` or unstructured stdlib logging),
  emit traces and metrics via OpenTelemetry, and report unhandled errors to Sentry.
- Configuration MUST be modeled with Pydantic v2 + `pydantic-settings`. Ad-hoc `os.environ`
  reads scattered through the codebase are forbidden.

**Rationale**: Consistent typing, formatting, and structured observability are what make a broad
system legible and debuggable; enforcing them at the gate keeps quality from eroding under scope.

### II. Architecture (Hexagonal, Proportionate, Open for Extension)

- Domain logic MUST be isolated from frameworks and I/O via ports & adapters. The domain layer
  MUST NOT import FastAPI, SQLAlchemy, Celery, or any vendor SDK/driver.
- Layering MUST stay proportionate to the domain. Introduce a port, adapter, or abstraction only
  when a second implementation, a test seam, or a real I/O boundary justifies it — no layers that
  do not earn their place.
- Notification channels (Email, SMS, Push) MUST sit behind a single channel port using the
  strategy/adapter pattern. Adding a channel MUST mean adding exactly ONE new adapter with ZERO
  edits to existing channel adapters or the dispatch core. Needing to modify existing channel
  code to add a channel is a Constitution violation (Open/Closed).
- SQLAlchemy table models are shared infrastructure behind repository ports; they are persistence
  details, not the domain itself.

**Rationale**: Isolation keeps the resilience and channel logic testable without real I/O, and the
Open/Closed channel boundary is the headline extensibility property this project demonstrates.

### III. Background Processing (Celery, Mixed Workload, Sync Seam)

- Background work MUST run on Celery with RabbitMQ as the broker.
- The workload is deliberately MIXED and MUST be routed to two pools:
  - I/O-bound tasks (the channel sends) → **threads** pool. (`psycopg` v3 is natively thread-safe, so
    no green-threading monkey-patching is needed; a **gevent** pool with `psycogreen` is the documented
    higher-concurrency alternative.)
  - CPU-bound tasks → **prefork** pool. The canonical CPU-bound task aggregates seeded usage data
    (~1,000 users × ~100,000 usage events each) into per-UTC-hour buckets to produce a usage
    bar-graph (one bar per UTC hour) before a push.
- Celery tasks MUST use a SEPARATE synchronous SQLAlchemy engine (`psycopg`, i.e. psycopg3). They MUST NOT use
  the API's async `asyncpg` engine or its sessions. Table models are shared across API and
  workers; engines and sessions are NOT.
- The README MUST document that ARQ or TaskIQ would be preferable for a fully-async service (no
  sync seam), and that Celery was chosen here deliberately for the mixed CPU+I/O workload and its
  ecosystem.

**Rationale**: A real mixed CPU+I/O workload is the reason Celery's two pool types exist; the
sync-engine seam is the correct, honest way to bridge a sync worker to async-first table models.

### IV. Resilience (First-Class — The Core Learning Goal)

- Channel adapters MUST simulate real-world conditions: artificial latency, randomly injected
  failures, simulated HTTP 429 rate-limits, and timeouts.
- Every outbound send MUST be protected by retries with exponential backoff, a circuit breaker
  (per channel/destination), and idempotency keys that prevent duplicate sends on retry.
- The send lifecycle MUST be modeled explicitly: `queued → sent → delivered | failed`. Every
  status transition MUST be persisted as append-only history and never silently overwritten.
- The simulated failure modes (backoff, breaker open/half-open/close, idempotent replay) MUST be
  covered by tests.

**Rationale**: Resilience is the core learning goal; simulating failure and persisting every
transition is what turns "it usually works" into a system whose behavior under failure is provable.

### V. Testing (Real Postgres + Broker, Mocked HTTP, Non-Negotiable)

- Tests MUST use `pytest` + `pytest-asyncio`, exercising the API through `httpx.AsyncClient`.
- Integration tests MUST run against a REAL PostgreSQL provisioned by Testcontainers — a
  session-scoped container with per-test transaction-rollback isolation. The database MUST NOT be
  mocked, faked, or swapped for SQLite.
- Tests that exercise background-task routing MUST run against a REAL RabbitMQ broker provisioned by
  Testcontainers, driving REAL workers — the broker MUST NOT be mocked or run in eager mode. (Rows
  written by a separate worker process are isolated by truncation rather than transaction rollback.)
- The HTTP layer of external channel calls MUST be mocked with `respx`, not by monkeypatching
  adapter internals.
- Coverage MUST be reported to Coveralls from CI.

**Rationale**: Testing against the real database catches the bugs SQLite and mocks hide, while
mocking only the external HTTP boundary keeps the resilience logic under genuine test.

### VI. Security (Tokens, Hashing, Secrets)

- Authentication MUST use OAuth2 with JWTs verified via `PyJWT`. `python-jose` MUST NOT be used.
- Passwords MUST be hashed with argon2 or bcrypt. Plaintext or reversible password storage is
  forbidden.
- Secrets and credentials MUST be supplied via `pydantic-settings` / environment variables. They
  MUST NEVER be hard-coded or committed to source control.

**Rationale**: These are the few security choices that are non-negotiable for any credible service;
fixing the library and hashing decisions up front prevents the common, costly mistakes.

### VII. Operations (Docker, GitHub Actions, One Process Model per Environment)

- CI and CD MUST both run on GitHub Actions.
- The named environments are `dev` and `prod`. Both run in Docker. Tests use Testcontainers, NOT
  the dev/prod compose stack.
- Exactly ONE API process model is active in a given running deployment — gunicorn-managed uvicorn
  workers OR a single-uvicorn process scaled by Kubernetes — never both in the same deployment:
  - **prod**: Kubernetes-scaled single-uvicorn pods (one uvicorn process per pod; Kubernetes
    performs horizontal scaling; gunicorn is NOT layered on top). CD deploys to this model.
  - **dev**: either model MAY be used as a developer convenience, but only one at a time.
- The ASGI server MUST be uvicorn with uvloop + httptools.
- Celery workers are SEPARATE processes in every environment, orthogonal to the API process model.
- Schema changes MUST go through Alembic migrations; manual or out-of-band DDL is forbidden.

**Rationale**: Mixing two process-management strategies in one deployment doubles the failure modes
for no benefit; pinning one model per environment keeps scaling behavior predictable.

## Technology Stack (Authoritative & Non-Negotiable)

The breadth below is a DELIBERATE portfolio/learning choice. Reviews, planning steps, and the
Constitution Check MUST NOT flag the observability stack, Celery/RabbitMQ background processing, or
the CI/CD pipeline as over-engineering, and MUST NOT simplify them away. Keep every piece clean and
proportionate — and keep all of it.

- **Language / packaging**: Python, managed with `uv` (dependencies + Python versions).
- **API / web**: FastAPI; uvicorn (uvloop + httptools) as the ASGI server; Pydantic v2 +
  `pydantic-settings`.
- **Data**: PostgreSQL; SQLAlchemy 2.0 async with `asyncpg` (API); a separate synchronous engine
  with `psycopg` v3 (psycopg3) (Celery workers); Alembic migrations.
- **Background**: Celery with RabbitMQ broker; prefork pool (CPU-bound) + threads pool (I/O-bound;
  gevent + psycogreen is the documented higher-concurrency alternative).
- **Resilience**: exponential-backoff retries, circuit breaker, idempotency keys, persisted send
  lifecycle (`queued → sent → delivered | failed`).
- **Observability**: `structlog` (logging), OpenTelemetry (tracing + metrics), Sentry (errors).
- **Security**: OAuth2 + `PyJWT`; argon2 or bcrypt password hashing; secrets via environment.
- **Testing**: `pytest`, `pytest-asyncio`, `httpx.AsyncClient`, Testcontainers (real Postgres +
  RabbitMQ), `respx` (external HTTP), Coveralls (coverage).
- **Quality tooling**: `ruff` (lint + format) and `mypy`, enforced via pre-commit and CI.
- **Frontend**: React.
- **Ops**: Docker (dev + prod), GitHub Actions (CI + CD), Kubernetes (prod API scaling).

## Development Workflow & Quality Gates

- **Repository layout**: a monorepo with `backend/` (the FastAPI service) and `frontend/` (the
  React app) at the root.
- **Pre-commit**: MUST run `ruff` (lint + format) and `mypy`; a failing hook blocks the commit.
- **CI (GitHub Actions)**: MUST run `ruff`, `mypy`, and the full `pytest` suite (with the
  Testcontainers Postgres + RabbitMQ) and publish coverage to Coveralls. A red pipeline blocks merge.
- **CD (GitHub Actions)**: deploys `prod` as Kubernetes-scaled single-uvicorn pods.
- **Migrations**: any model change MUST ship with its Alembic revision in the same PR.
- **Planning gate**: every feature plan MUST pass the Constitution Check before implementation
  begins; unjustified deviations block the plan.

## Governance

- This Constitution supersedes ad-hoc practices. Where a rule here conflicts with convenience, the
  Constitution wins.
- Amendments MUST be made by a PR that edits this file, states the rationale, and bumps the version
  per the policy below.
- **Versioning policy** (semantic): MAJOR = backward-incompatible removal or redefinition of a
  principle or governance rule; MINOR = a new principle/section or materially expanded guidance;
  PATCH = clarifications, wording, or typo fixes with no change in meaning.
- **Compliance**: every feature plan MUST pass the Constitution Check gate, and every PR review
  MUST verify compliance with these principles. Genuine deviations MUST be recorded in the plan's
  Complexity Tracking with justification. The deliberate stack breadth defined above is NOT a
  deviation and MUST NOT be logged there.
- Runtime guidance for AI agents lives in `CLAUDE.md`; it MUST be kept consistent with this
  Constitution.

**Version**: 1.2.0 | **Ratified**: 2026-06-19 | **Last Amended**: 2026-06-20
