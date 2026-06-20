---
description: "Task list for System Liveness Walking Skeleton"
---

# Tasks: System Liveness Walking Skeleton

**Input**: Design documents from `specs/001-system-liveness/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: REQUIRED. The constitution (Principle V) makes testing non-negotiable and the spec
explicitly requires it (FR-012, FR-017, US4, SC-008/009). Integration tests run against real
Postgres + RabbitMQ via Testcontainers (no DB mocking, no Celery eager mode); respx is reserved for
external HTTP (none in this slice).

**Organization**: Tasks are grouped by user story. Paths follow the hexagonal layout in plan.md
(`backend/app/...`, `frontend/...`).

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: parallelizable (different files, no dependency on an incomplete task)
- **[Story]**: US1–US4 (user-story phases only)

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and tooling.

- [x] T001 Create monorepo structure (`backend/`, `frontend/`) and initialize the backend uv project in `backend/pyproject.toml` (Python 3.13; deps: fastapi, uvicorn[standard], sqlalchemy>=2, asyncpg, psycopg[binary], pydantic, pydantic-settings, alembic, celery, kombu, structlog, opentelemetry-sdk, sentry-sdk; dev: pytest, pytest-asyncio, httpx, testcontainers[postgres,rabbitmq], respx, coverage, ruff, mypy, pre-commit)
- [x] T002 [P] Configure ruff (lint + format) and mypy (strict for `domain/`+`application/`) in `backend/pyproject.toml`, and add `.pre-commit-config.yaml` (ruff, ruff-format, mypy)
- [x] T003 [P] Implement settings in `backend/app/settings.py` (pydantic-settings: `database_url_async`, `database_url_sync`, `broker_url`, `otel_*`, `sentry_dsn`, `readiness_check_timeout_s`, `smoke_timeout_s` with spec defaults)
- [x] T004 [P] Create package skeleton with `__init__.py` for `backend/app/{domain,ports,application,adapters,infra,api,tasks,cli}` and `backend/tests/{unit,integration,factories}`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared core every user story depends on.

**⚠️ CRITICAL**: No user story work begins until this phase is complete.

- [x] T005 [P] Define domain models in `backend/app/domain/health.py` (`HealthStatus` enum, `SubsystemCheck`, `ReadinessReport` — pure, no framework imports) per data-model.md
- [x] T006 [P] Define ports in `backend/app/ports/probes.py` (`BrokerProbe`, `WorkerProbe` Protocols) and `backend/app/ports/repositories.py` (`LivenessCompletionWriter` sync, `LivenessCompletionReader` async)
- [x] T007 [P] Implement engines: `backend/app/infra/db/async_engine.py` (`create_async_engine`, asyncpg) and `backend/app/infra/db/sync_engine.py` (`create_engine`, psycopg v3)
- [x] T008 Implement ORM model `LivenessCompletion` in `backend/app/adapters/persistence/models.py` (table `liveness_completion`: `id`, `correlation_id` UUID, `pool_label` CHECK in ('cpu','io'), `created_at`; unique `(correlation_id, pool_label)`; index `(correlation_id)`)
- [x] T009 Initialize Alembic (`backend/migrations/env.py` wired to the sync engine + models metadata) and create revision `backend/migrations/versions/0001_liveness_completion.py` creating the table (depends on T008)
- [x] T010 [P] Implement telemetry wiring in `backend/app/infra/telemetry.py` (structlog JSON renderer; OpenTelemetry tracer provider + configurable exporter; sentry-sdk init from settings; idempotent) (FR-016)
- [x] T011 Configure the Celery app in `backend/app/tasks/celery_app.py` (`broker_url` from settings, `result_backend=None`, `task_ignore_result=True`, queues `cpu`+`io`, task routes) **and register a `worker_process_init` signal that initializes telemetry (`app.infra.telemetry`) on each worker process** (FR-016, FR-019)
- [x] T012 Implement composition root `backend/app/bootstrap.py` (bind ports → adapters) and `backend/app/main.py` (FastAPI app; lifespan initializes telemetry; include health router) (depends on T006, T010)
- [x] T013 Build the test harness in `backend/tests/conftest.py`: session-scoped Testcontainers **Postgres + RabbitMQ**; async/sync session fixtures; per-test transaction-rollback isolation for DB-bound tests; a worker fixture that starts **both** pools — `cpu` (prefork, `-n cpu@%h -Q cpu`) and `io` (threads, `-n io@%h -Q io`); a truncation helper for cross-process tests (depends on T007, T011)

**Checkpoint**: Foundation ready — user stories can begin.

---

## Phase 3: User Story 1 - Aggregate readiness endpoint + probes (Priority: P1) 🎯 MVP

**Goal**: `/livez` (process-only), `/readyz` (process + DB), `/health` (DB + broker + per-pool worker pings) with correct status codes and an always-present per-subsystem breakdown.

**Independent Test**: With deps + both worker pools up, `/health`→200 with all checks passing; stop Postgres → `/readyz`+`/health` 503 while `/livez` stays 200; stop a worker pool or the broker → `/health` 503 naming the failure; responses are bounded and never block on a job.

### Tests for User Story 1

- [x] T014 [P] [US1] Unit tests for the aggregate readiness logic with fake `BrokerProbe`/`WorkerProbe` in `backend/tests/unit/test_readiness_aggregate.py` (all-pass → healthy; any-fail → not_healthy; bounded, no hang; assert the readiness path enqueues no task — no `apply_async` — per FR-015)
- [x] T015 [P] [US1] Integration test `backend/tests/integration/test_livez_readyz.py`: `/livez` always 200; `/readyz` 200 when DB reachable and 503 when DB unreachable while `/livez` stays 200 (real Postgres)
- [x] T016 [P] [US1] Integration test `backend/tests/integration/test_health_aggregate.py`: all-healthy → 200 with both worker pools passing; broker down → 503; one worker pool down → 503; body always carries the breakdown; **assert `/livez` and `/readyz` stay 2xx while `/health` → 503 when worker pools are down (probe decoupling, FR-014/SC-010); assert the normal-case `/health` response is within the configured normal bound (SC-005, <1s)** (real Postgres + RabbitMQ + both pools)

### Implementation for User Story 1

- [x] T017 [P] [US1] Implement `BrokerProbe` adapter in `backend/app/adapters/probes/celery_broker.py` (kombu `connection.ensure_connection`, bounded)
- [x] T018 [P] [US1] Implement `WorkerProbe` adapter in `backend/app/adapters/probes/celery_worker.py` (`app.control.ping(timeout=…)`; group responders by nodename prefix `cpu@`/`io@` → `worker_pool_cpu`/`worker_pool_io`)
- [x] T019 [US1] Implement liveness + readiness use cases in `backend/app/application/liveness.py` (process-only liveness; process + DB readiness via async `SELECT 1`) (depends on T007)
- [x] T020 [US1] Implement the aggregate readiness use case in `backend/app/application/readiness_aggregate.py` (DB `SELECT 1` async + broker + per-pool worker pings concurrently via `asyncio.gather`; offload blocking kombu/control calls with `asyncio.to_thread`; per-check `asyncio.wait_for`; never enqueue/await a job) (depends on T017, T018, T019)
- [x] T021 [P] [US1] Implement Pydantic response schemas in `backend/app/api/schemas.py` (live/ready/aggregate `ReadinessReport`) per `contracts/health-api.yaml`
- [x] T022 [US1] Implement the health router in `backend/app/api/routers/health.py` (`GET /livez` 200; `GET /readyz` 200/503; `GET /health` 200/503 with body) + `backend/app/api/deps.py`; register the router in `main.py` (depends on T020, T021, T012)
- [x] T023 [US1] Bind the probe/use-case adapters in `backend/app/bootstrap.py` for the health router (depends on T012, T017–T020)

**Checkpoint**: US1 fully functional and independently testable (MVP).

---

## Phase 4: User Story 2 - One-command local bring-up (Priority: P2)

**Goal**: `docker compose up` starts every service healthy, with the migration applied.

**Independent Test**: From a clean checkout, `docker compose up` → all services healthy, `liveness_completion` table present, `/readyz` 200.

- [x] T024 [US2] Add `backend/Dockerfile` (uv-based; service entrypoints for API + workers) with a startup entrypoint that runs `alembic upgrade head` before launching the API (FR-008)
- [x] T025 [US2] Author `docker-compose.yml` at repo root: services `api`, `cpu-worker` (`--pool=prefork -n cpu@%h -Q cpu -c 4`), `io-worker` (`--pool=threads -n io@%h -Q io -c 20`), `postgres`, `rabbitmq:4-management`, `frontend`; with `depends_on` conditions and healthchecks
- [x] T026 [US2] Add the `api` service healthcheck against `/readyz` and verify the one-command bring-up against `quickstart.md` (all services healthy, migration applied)

**Checkpoint**: US2 — one documented command brings everything up healthy.

---

## Phase 5: User Story 3 - Frontend liveness view (Priority: P3)

**Goal**: A minimal page that renders the `/health` verdict + per-subsystem breakdown, and an unavailable/unknown state.

**Independent Test**: With `/health` serving a known state, the page shows it; stop Postgres → non-healthy shown; stop the API → "unavailable/unknown" (not blank, not false-healthy).

- [x] T027 [P] [US3] Scaffold the frontend (Vite + React + TS) in `frontend/` (`package.json` with `dev`/`build`, `vite.config.ts`, `index.html`, `src/main.tsx`)
- [x] T028 [P] [US3] Implement the health API client in `frontend/src/api/health.ts` (fetch `GET /health`; surface non-200 and network errors distinctly)
- [x] T029 [US3] Implement `frontend/src/components/HealthView.tsx` (render overall verdict + per-subsystem breakdown; non-healthy state; unavailable/unknown on fetch failure) and mount it in `main.tsx` (depends on T028)
- [x] T030 [P] [US3] Component test `frontend/src/components/HealthView.test.tsx` (vitest + testing-library): healthy, non-healthy, and unavailable states (FR-010/011)

**Checkpoint**: US3 — frontend shows live status from `/health`.

---

## Phase 6: User Story 4 - Quality gate, smoke check & telemetry verification (Priority: P3)

**Goal**: The on-demand smoke check round-trips a real task through each pool (sync-write / async-read completion); the lint/type/test gate passes locally and in CI; telemetry emission is asserted.

**Independent Test**: `python -m app.cli.smoke` exits 0 when both pool rows appear (1 otherwise); `pytest`, `ruff`, `mypy` all green locally and in CI; telemetry assertions pass.

### Implementation for User Story 4

- [x] T031 [P] [US4] Implement persistence repos: sync writer `backend/app/adapters/persistence/sync_repo.py` (`LivenessCompletionWriter` via psycopg session) and async reader `backend/app/adapters/persistence/async_repo.py` (`LivenessCompletionReader.both_completed` via asyncpg) (depends on T008)
- [x] T032 [US4] Implement the `liveness_ping(correlation_id, pool_label)` task in `backend/app/tasks/liveness.py` (no-op; writes `LivenessCompletion` via the sync writer); register on `celery_app` with cpu/io routing (depends on T011, T031)
- [x] T033 [US4] Implement the smoke use case in `backend/app/application/smoke.py` (generate UUID4 `correlation_id`; `apply_async(queue="cpu")` + `apply_async(queue="io")`; poll `reader.both_completed` via `asyncio.wait_for` up to `smoke_timeout_s`) (depends on T031, T032)
- [x] T034 [US4] Implement the smoke CLI `backend/app/cli/smoke.py` (`python -m app.cli.smoke`; `asyncio.run`; **exit 0** on both rows, **exit 1** on timeout/failure with stderr naming the missing pool) + a `smoke-check` console script in `pyproject.toml` (depends on T033)

### Tests for User Story 4

- [x] T035 [P] [US4] Integration test `backend/tests/integration/test_smoke_roundtrip.py`: real broker + both pools; run the smoke use case; assert both completion rows for the `correlation_id`; cleanup via truncation (real Postgres + RabbitMQ)
- [x] T036 [P] [US4] Integration test `backend/tests/integration/test_telemetry.py`: structured startup log line emitted; trace span recorded around a `/health` request (InMemorySpanExporter); Sentry client initialized (FR-017)

### CI/CD for User Story 4

- [x] T037 [US4] Add `.github/workflows/ci.yml`: install uv + Python 3.13; `ruff check` + `ruff format --check`; `mypy`; `pytest` with Testcontainers (Postgres + RabbitMQ) on the runner host; publish coverage to Coveralls
- [x] T038 [P] [US4] Create Kubernetes manifests in `deploy/k8s/` (`deployment.yaml` + `service.yaml` for the API; `livenessProbe` → `/livez`, `readinessProbe` → `/readyz`; probes never gated on workers) (FR-018, FR-020)
- [x] T039 [US4] Add `.github/workflows/cd.yml`: build the image and `kubectl apply` the `deploy/k8s/` manifests (single-uvicorn pods); include a manifest validation step (`kubectl apply --dry-run=client` / kubeconform) (SC-011) (depends on T038)

**Checkpoint**: US4 — smoke check green, quality gate green locally and in CI, deploy manifests in place.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [x] T040 [P] Create `README.md` documenting the Celery rationale (ARQ/TaskIQ preferable for a fully-async service; Celery chosen for the mixed CPU+I/O workload + ecosystem) and the gevent+psycogreen higher-concurrency alternative to the threads I/O pool (constitution Principle III)
- [x] T041 [P] Configure coverage in `backend/pyproject.toml` (`[tool.coverage]`) and finalize Coveralls; re-run `quickstart.md` validation end-to-end
- [x] T042 Run the full gate locally (`ruff`, `mypy`, `pytest`) and `python -m app.cli.smoke`; fix any findings (SC-008)
- [x] T043 [P] Pin all dependencies for reproducible builds (constitution v1.3.1, Principle I): no floating tags — base images (`python`, `node`, `postgres`, `rabbitmq`) and `uv` pinned to explicit **patch version + digest** across `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`, and `tests/conftest.py`; deployed image referenced immutably (git-SHA tag) via `deploy/k8s/deployment.yaml` + CD `kubectl set image`; GitHub Actions on released major tags

---

## Dependencies & Execution Order

- **Setup (P1)** → **Foundational (P2)** → user stories.
- **US1 (P3)**: depends only on Foundational. **MVP.**
- **US2 (P2-priority)**: depends on Foundational + US1 (compose healthcheck uses `/readyz`).
- **US3 (P3)**: depends on US1 (`/health` contract; can stub against `contracts/health-api.yaml`).
- **US4 (P3)**: smoke path (T031–T035) depends on Foundational only; the telemetry test (T036) and CI (T037) depend on US1 (`/health`); the k8s manifests + CD (T038–T039) depend on the probe endpoints (US1, FR-018/FR-020).
- **Polish (P7)**: after the desired stories.

### Within each story
- Tests are written to fail first, then implementation makes them pass.
- Models → ports/adapters → use cases → API/CLI → bootstrap wiring.

## Parallel Opportunities

- **Setup**: T002, T003, T004 in parallel after T001.
- **Foundational**: T005, T006, T007, T010 in parallel; T008→T009 sequential; T011 parallel; T012/T013 after their deps.
- **US1 tests**: T014, T015, T016 in parallel. **US1 impl**: T017, T018, T021 in parallel; then T019→T020→T022→T023.
- **US4**: T031 then T032; T035, T036 in parallel; T037 and T038 in parallel; T039 after T038.
- **Polish**: T040, T041 in parallel; then T042.

## Implementation Strategy

- **MVP**: Phase 1 + Phase 2 + Phase 3 (US1) → working `/livez`, `/readyz`, `/health`. Stop and validate.
- **Incremental**: add US2 (one-command bring-up) → US4 (smoke + gate + CI) → US3 (frontend) → Polish.
  (US4 before US3 is reasonable since the CI gate guards everything; reorder freely — stories are independent.)

## Notes

- [P] = different files, no incomplete dependency.
- Tests use real Postgres + RabbitMQ (Testcontainers); never mock the DB; never run Celery eager.
- The aggregate `/health` must offload blocking broker/worker calls via `asyncio.to_thread` and stay
  bounded; k8s probes (`/livez`, `/readyz`) must never be gated on workers.
- Ship the Alembic revision (T009) in the same PR as the model (T008).
- Commit after each task or logical group.
