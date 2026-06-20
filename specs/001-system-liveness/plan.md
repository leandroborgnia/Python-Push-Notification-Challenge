# Implementation Plan: System Liveness Walking Skeleton

**Branch**: `001-system-liveness` | **Date**: 2026-06-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-system-liveness/spec.md`

## Summary

Build the thinnest end-to-end vertical that proves every subsystem is wired and alive. Three HTTP
health surfaces with distinct semantics — a process-only **liveness** probe (`/livez`), a process+DB
**readiness** probe (`/readyz`), and a rich **aggregate** health endpoint (`/health`) that additionally
pings a worker on each background-processing pool — plus an on-demand **smoke check** that routes a
real no-op task through the broker to each pool (prefork CPU + threads I/O), where the worker writes a
correlation-keyed completion row via the **sync (psycopg v3)** engine and the check reads it back via
the **async (asyncpg)** layer within a bounded timeout. A minimal React/Vite page renders `/health`.
Telemetry (structlog + OpenTelemetry + Sentry) is wired at startup and asserted in-process. Everything
is exercised by pytest against ephemeral Testcontainers (Postgres + RabbitMQ) and gated by ruff + mypy
in CI, with coverage to Coveralls.

All technology/architecture choices are fixed by the constitution and the spec's Clarifications
(Sessions 2026-06-19 and 2026-06-20). This plan maps them onto concrete structure and does not
re-decide them. Items the spec/constitution leave open are listed under
**[Flagged Underspecifications](#flagged-underspecifications)** rather than silently invented.

## Technical Context

**Language/Version**: Python **3.13** (confirmed; `requires-python = ">=3.13"`, single-version CI).
Frontend: TypeScript + React + Vite.

**Primary Dependencies**: FastAPI, uvicorn (uvloop + httptools), SQLAlchemy 2.0, asyncpg (API engine),
psycopg v3 (worker engine), Pydantic v2 + pydantic-settings, Alembic, Celery + RabbitMQ (kombu),
structlog, OpenTelemetry SDK, sentry-sdk. Tooling: uv, ruff, mypy, pre-commit. Tests: pytest,
pytest-asyncio, httpx.AsyncClient, Testcontainers (Postgres **and** RabbitMQ, per constitution v1.2.0),
respx, coverage/Coveralls.

**Storage**: PostgreSQL. One Alembic-managed table for this slice: `liveness_completion` (the smoke
check's correlation-keyed completion record). Written by workers via the sync engine; read by the API
via the async engine.

**Testing**: pytest + pytest-asyncio; integration tests against real Postgres + RabbitMQ via
Testcontainers; the readiness probes/aggregate logic tested through ports (fakes for broker/worker)
for unit-level and against real infra for integration-level; the smoke check tested end-to-end with a
real broker and real in-test worker processes. respx reserved for future external HTTP (none in this
slice).

**Target Platform**: Linux containers. Dev: `docker compose up`. Prod: Kubernetes (single-uvicorn
pods) via Deployment/Service manifests in `deploy/k8s/` (`/livez` → livenessProbe, `/readyz` →
readinessProbe). Celery workers are separate processes.

**Project Type**: Web application (monorepo: `backend/` + `frontend/`).

**Performance Goals** (from spec Success Criteria): aggregate `/health` < 1s normal, < 5s under a
failing dependency (never hangs, never blocks on a job); smoke-check round-trip < 10s per pool;
one-command bring-up healthy < 5 min.

**Constraints**: Async all the way — no blocking calls in the API event loop (blocking broker/worker
control calls MUST be offloaded via `asyncio.to_thread` with bounded timeouts). k8s probes MUST NOT be
gated on workers or the broker. Background tasks run with `ignore_result=True` (no result backend).
Never edit applied migrations. Secrets via pydantic-settings/env.

**Scale/Scope**: Walking skeleton — 2 background pools (cpu/io), 3 HTTP health surfaces, 1 table, 1
smoke CLI, 1 minimal frontend page. No channels, auth, or analytics (explicitly out of scope).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| # | Principle | Status | How this plan complies |
|---|-----------|--------|------------------------|
| I | Code Quality (typed, linted, observable, pinned) | ✅ PASS | ruff + mypy via pre-commit & CI; structlog/OTel/Sentry wired at startup (FR-016) and asserted (FR-017); config via pydantic-settings; **pinned builds** — committed lockfiles; base images & `uv` pinned to patch version + digest; deployed image by immutable git-SHA tag; Actions pinned to commit SHAs (v1.3.1). |
| II | Architecture (hexagonal, proportionate, open/closed) | ✅ PASS | Domain `ReadinessReport`/`SubsystemCheckResult` are framework-free; `BrokerProbe`/`WorkerProbe`/repository **ports** isolate I/O; adapters under `adapters/`. No channel code yet (out of scope) — extension points respected, nothing in the dispatch core to edit. |
| III | Background Processing (Celery, mixed workload, sync seam) | ✅ PASS | Celery + RabbitMQ; `cpu` queue → prefork, `io` queue → threads; workers use the **sync psycopg v3** engine, API uses **asyncpg**; `ignore_result=True`. |
| IV | Resilience (first-class) | ✅ PASS (scoped) | This slice models the liveness round-trip + bounded/timeout checks; full retry/backoff/circuit-breaker belongs to the channel features (out of scope) — no resilience code is removed or precluded. |
| V | Testing (real Postgres, mocked HTTP, non-negotiable) | ✅ PASS | Real Postgres via Testcontainers, no DB mocking; real broker for the smoke check; respx reserved for external HTTP; coverage → Coveralls. Per constitution v1.2.0, Testcontainers covers Postgres + RabbitMQ (real broker, no eager mode). |
| VI | Security (tokens, hashing, secrets) | ✅ PASS (scoped) | No auth in this slice (spec out-of-scope); secrets via env only; no secrets in code. |
| VII | Operations (Docker, GH Actions, one process model/env) | ✅ PASS | `docker compose up` (dev); k8s single-uvicorn pods (prod) with `/livez`+`/readyz`; CI+CD via GitHub Actions; Alembic migration ships with the model. |

**Deliberate stack breadth** (observability, Celery, CI/CD) is retained per the constitution and is
**not** logged as complexity. No gate violations → Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-system-liveness/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions & rationale
├── data-model.md        # Phase 1 — liveness_completion + health DTOs
├── quickstart.md        # Phase 1 — bring-up & validation guide
├── contracts/           # Phase 1 — health HTTP contract + smoke CLI contract
│   ├── health-api.yaml
│   └── smoke-check-cli.md
└── tasks.md             # Phase 2 — /speckit.tasks (NOT created here)
```

### Source Code (repository root)

```text
backend/
  app/
    domain/
      health.py              # HealthStatus enum, SubsystemCheck, ReadinessReport (pure, no frameworks)
    ports/
      probes.py              # BrokerProbe, WorkerProbe (Protocols)
      repositories.py        # LivenessCompletionReader (async), LivenessCompletionWriter (sync)
    application/
      liveness.py            # liveness (process-only) + readiness (process + DB) use cases
      readiness_aggregate.py # aggregate: DB + broker + per-pool worker pings (bounded, concurrent)
      smoke.py               # on-demand smoke check: dispatch per pool + poll completion (async)
    adapters/
      probes/
        celery_broker.py     # BrokerProbe via kombu connection.ensure_connection
        celery_worker.py     # WorkerProbe via app.control.ping → group by nodename prefix
      persistence/
        models.py            # SQLAlchemy ORM: LivenessCompletion (shared by both engines)
        async_repo.py        # AsyncSession reader (API/smoke read)
        sync_repo.py         # sync Session writer (Celery task write)
    infra/
      db/async_engine.py     # create_async_engine (asyncpg)
      db/sync_engine.py      # create_engine (psycopg v3)
      telemetry.py           # structlog + OpenTelemetry + Sentry wiring (idempotent init)
    api/
      routers/health.py      # GET /livez, GET /readyz, GET /health
      schemas.py             # Pydantic DTOs for health responses
      deps.py                # DI wiring into application use cases
    tasks/
      celery_app.py          # Celery app: ignore_result=True, queues cpu/io, task routes
      liveness.py            # liveness_ping task (no-op → writes LivenessCompletion via sync repo)
    cli/
      smoke.py               # `python -m app.cli.smoke` → asyncio.run(smoke check); exit 0/1
    bootstrap.py             # composition root: bind ports → adapters
    main.py                  # FastAPI app (uvicorn target: app.main:app); telemetry init on startup
    settings.py              # pydantic-settings (DB URLs, broker URL, OTel/Sentry, timeouts)
  migrations/
    env.py
    versions/0001_liveness_completion.py
  tests/
    unit/                    # domain + application logic with fake ports
    integration/
      test_livez_readyz.py   # probe semantics incl. DB-down (real Postgres)
      test_health_aggregate.py
      test_smoke_roundtrip.py# real broker + in-test cpu/io workers
      test_telemetry.py      # structured startup log, readiness trace span, Sentry init
    factories/
    conftest.py              # Testcontainers (Postgres + RabbitMQ), engine/session fixtures
  pyproject.toml             # uv project, ruff/mypy config, console entrypoints
  Dockerfile
frontend/
  src/
    main.tsx
    api/health.ts            # fetch GET /health
    components/HealthView.tsx# render verdict + per-subsystem breakdown; unavailable state
  package.json               # Vite scripts: dev / build
  vite.config.ts
docker-compose.yml           # api + cpu worker + io worker + postgres + rabbitmq + frontend
.github/workflows/
  ci.yml                     # ruff + mypy + pytest (Testcontainers) + Coveralls
  cd.yml                     # build image + kubectl apply deploy/k8s manifests
deploy/k8s/
  deployment.yaml            # API Deployment: livenessProbe→/livez, readinessProbe→/readyz
  service.yaml               # API Service
```

**Structure Decision**: Web-application (Option 2) hexagonal layout per CLAUDE.md, with dependencies
pointing inward toward `domain/`. New code lands in the layer the constitution mandates: health
verdict logic in `domain/`+`application/`, all I/O (broker/worker/DB) behind `ports/` with adapters in
`adapters/`, HTTP surface in `api/`, the Celery app + no-op task in `tasks/`, and the smoke entrypoint
in `cli/`. The dual-engine seam is explicit: `async_repo.py`/`async_engine.py` (API reads) vs
`sync_repo.py`/`sync_engine.py` (worker writes), sharing `models.py`.

## Flagged Underspecifications

Per the request to flag rather than invent. Items 1–2 were escalated and are now **resolved**
(2026-06-20); 3–5 are plan-level defaults I chose (documented in research.md) and noted for visibility.

1. **Python version** — ✅ RESOLVED (2026-06-20): **Python 3.13** confirmed
   (`requires-python = ">=3.13"`, single-version CI).
2. **RabbitMQ in the test suite** — ✅ RESOLVED (2026-06-20): confirmed — **RabbitMQ Testcontainer +
   in-test workers** for the smoke e2e, and the **constitution (v1.2.0) now mandates Testcontainers for
   both Postgres and RabbitMQ**. The in-test worker fixture starts **both** the `cpu` and `io` pools,
   since readiness pings both. Cleanup is by truncation (cross-process writes are not covered by
   transaction rollback).
3. **Smoke-check invocation surface** — spec deferred to planning. **Decided: a CLI/management command**
   (`python -m app.cli.smoke`, also a console script) — *not* a public HTTP endpoint (avoids exposing a
   job-triggering surface). CI/deploy invoke it; an integration test drives the same use case.
4. **Per-pool worker ping mechanism** — **Decided:** broadcast `app.control.ping(timeout=…)`, group
   responders by **nodename prefix**, and require at least one `cpu@*` and one `io@*` responder. This
   requires workers to be started with pool-identifying nodenames (`-n cpu@%h`, `-n io@%h`) — already
   applied to the CLAUDE.md worker commands and the docker-compose worker services (T025).
5. **Smoke-test DB cleanup** — transaction-rollback isolation cannot cover a row written by a *separate
   worker process*. **Decided:** the smoke end-to-end test cleans up via truncation, not rollback;
   rollback isolation still applies to the readiness/aggregate tests.

## Complexity Tracking

> No Constitution Check violations. The broad stack is deliberate per the constitution and is not a
> violation. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |

## Phase Outputs

- **Phase 0** → [research.md](./research.md): resolves Python version handling, endpoint contract
  shapes, the async-offload pattern for blocking Celery control calls, per-pool ping strategy, smoke
  surface, correlation-key design, and the test topology (Testcontainers Postgres+RabbitMQ; rollback
  vs truncation; ports for fakes; telemetry in-process verification).
- **Phase 1** → [data-model.md](./data-model.md), [contracts/](./contracts/),
  [quickstart.md](./quickstart.md); agent context (`CLAUDE.md` SPECKIT marker) updated to reference
  this plan.
- **Phase 2** → `/speckit.tasks` will generate `tasks.md` (not produced by this command).
