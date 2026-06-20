# Phase 0 Research: System Liveness Walking Skeleton

All architecture is fixed by the constitution and the spec Clarifications; this file records the
**plan-level** decisions needed to implement them, plus the two items escalated to
[Flagged Underspecifications](./plan.md#flagged-underspecifications).

## R1. Python version

- **Decision**: Target **Python 3.13** (`requires-python = ">=3.13"`), single-version CI for now.
- **Rationale**: Fully supported by FastAPI, SQLAlchemy 2.0, asyncpg, psycopg v3, Celery 5, structlog,
  OpenTelemetry, and uv; latest stable with no blockers in the stack.
- **Status**: ✅ CONFIRMED (2026-06-20) — Python 3.13; pins `requires-python` + CI.
- **Alternatives**: 3.12 (fine, slightly older); 3.14 (too new for some C-extension wheels at this date).

## R2. Health surface topology & contract

- **Decision**: Three endpoints with distinct semantics (spec FR-001/014/018/020):
  - `GET /livez` — **liveness**, process-only. Always `200` if the process is up; never touches DB,
    broker, or workers. Body: `{"status":"alive"}`.
  - `GET /readyz` — **readiness**, process + DB. `200` when a `SELECT 1` succeeds, `503` when the DB is
    unreachable. Never gated on broker/workers. Minimal body.
  - `GET /health` — **aggregate**, rich. Runs shallow checks: DB `SELECT 1`, broker reachability, and a
    per-pool worker ping. `200` when all pass, `503` when any fails; **always** returns the full
    per-subsystem breakdown in the body.
- **Rationale**: Matches the liveness/readiness split (Session 2026-06-20) and the status-coded
  two-endpoint+aggregate decision (Session 2026-06-19). Separating `/livez` from `/readyz` prevents a
  DB outage from crash-looping the pod while still depooling it.
- **Alternatives rejected**: single combined probe (crash-loop risk); always-200 aggregate body-only
  (chosen against in Session 2026-06-19).

## R3. Keeping the event loop unblocked for broker/worker checks

- **Decision**: The aggregate check runs the **DB probe** natively async (asyncpg `SELECT 1`), and the
  **broker reachability** + **worker ping** via `await asyncio.to_thread(...)` because Celery/kombu
  control calls are synchronous. Wrap each subsystem check in `asyncio.wait_for(...)` with a per-check
  timeout and run them concurrently via `asyncio.gather`, bounding total latency.
- **Rationale**: Constitution "async all the way — no blocking calls in the event loop." `to_thread`
  offloads the blocking kombu I/O; per-check timeouts satisfy SC-004 (<5s, never hangs) and SC-005
  (<1s normal).
- **Alternatives**: an async AMQP client for broker checks (more deps, not needed); calling
  `control.ping` directly on the loop (rejected — blocks the loop).

## R4. Per-pool worker ping

- **Decision**: `app.control.ping(timeout=<short>)` broadcasts to all workers; collect responder
  **nodenames** and require ≥1 with prefix `cpu@` and ≥1 with `io@`. Workers are started with
  pool-identifying nodenames: `-n cpu@%h` (prefork, `-Q cpu`) and `-n io@%h` (threads, `-Q io`).
- **Rationale**: Avoids needing exact hostnames or a result backend; the ping uses only the broker.
  Nodename prefixes make "a worker on each pool" observable and testable.
- **Consequence**: CLAUDE.md worker commands gain `-n cpu@%h` / `-n io@%h` (Flagged #4); applied in tasks.
- **Alternatives**: `inspect().active_queues()` (heavier, also broadcast); targeting `destination=[...]`
  by exact node (brittle across hosts).

## R5. Smoke-check invocation surface

- **Decision**: A CLI/management command `python -m app.cli.smoke` (plus a `pyproject` console script),
  invoked in CI/deploy and runnable on demand. It is **not** a public HTTP endpoint. The same
  `application/smoke.py` use case is driven directly by an integration test.
- **Rationale**: Spec deferred this to planning and stated the check is "primarily a CI/deploy smoke
  test, runnable on demand." A CLI avoids exposing a job-triggering HTTP surface and keeps the readiness
  endpoint cheap/shallow (FR-015).
- **Alternatives**: internal HTTP endpoint (extra surface, risk of being polled); pytest-only (not
  runnable in deploy).

## R6. Smoke round-trip mechanics (results disabled)

- **Decision**: One Celery task `liveness_ping(correlation_id, pool_label)` registered once and
  dispatched per pool via `apply_async(queue="cpu")` and `apply_async(queue="io")`. With
  `ignore_result=True` and **no result backend**, the task records completion by writing a
  `LivenessCompletion` row (correlation_id, pool_label, created_at) through the **sync (psycopg v3)**
  repository. The CLI/use case polls for both rows via the **async (asyncpg)** reader using
  `asyncio.wait_for` up to a bounded timeout; success = both pool rows for this `correlation_id` appear.
- **Rationale**: Directly implements the Session 2026-06-19 (C) decision: real task → real broker →
  real worker → sync-write / async-read completion. Proves queue→pool routing **and** the dual-engine
  seam end-to-end.
- **Correlation key**: a `UUID4` generated per smoke invocation, passed into each task and stored on the
  row; the reader filters by it so concurrent/previous runs never cross-talk.
- **Alternatives**: Celery result backend (rejected by the spec); shared in-memory signal (not a real
  cross-process round-trip).

## R7. Test topology

- **Decision**:
  - **conftest** provisions a **session-scoped Postgres Testcontainer** (transaction-rollback isolation
    per test) and a **session-scoped RabbitMQ Testcontainer**.
  - A worker fixture starts **both** pools — `cpu` (prefork, `-n cpu@%h -Q cpu`) and `io` (threads,
    `-n io@%h -Q io`) — for every test that needs healthy worker pings (the aggregate `/health`
    all-healthy path) **and** for the smoke round-trip, since readiness pings both pools.
  - **Probe/aggregate logic** is unit-tested through `BrokerProbe`/`WorkerProbe` **fakes**; integration
    tests exercise real adapters.
  - `/readyz` DB-down is tested by pointing the readiness check at a closed/invalid connection (or
    stopping the container connection), asserting `503`; `/livez` stays `200`.
  - **Smoke end-to-end** test starts real `cpu` (prefork) and `io` (threads) workers (subprocess or
    background) against the RabbitMQ container, runs the smoke use case, asserts both completion rows.
    Cleanup via **truncation** (cross-process writes aren't covered by transaction rollback — Flagged #5).
- **Rationale**: Honors constitution Testing (real Postgres, no DB mocks) and the spec's "real broker →
  real worker." Ports keep fast unit tests possible without violating the no-mock-DB rule.
- **Alternatives**: Celery `task_always_eager` (rejected — not a real broker/worker round-trip; defeats
  the purpose); mocking the DB (forbidden).

## R8. Telemetry wiring & in-process verification

- **Decision**: `infra/telemetry.py` initializes structlog (JSON renderer), the OpenTelemetry SDK
  (tracer provider; OTLP exporter in prod, configurable), and `sentry-sdk` (DSN from settings; empty/
  disabled in dev/test). Init is idempotent and runs on FastAPI startup and Celery worker startup.
  Tests assert: a structured startup log line (capture via structlog test capture), a trace span around
  a `/health` request (in-memory `InMemorySpanExporter`), and that the Sentry client is initialized
  (assert `sentry_sdk.Hub.current.client is not None`, transport stubbed).
- **Rationale**: Implements FR-016/FR-017 (wire **and** verify) without external telemetry backends.
- **Alternatives**: wire-only (rejected in Session 2026-06-19 — chose verify too).

## R9. Settings, migrations, frontend

- **Settings** (pydantic-settings): `database_url_async` (asyncpg), `database_url_sync` (psycopg),
  `broker_url`, `otel_*`, `sentry_dsn`, and bounded-timeout knobs (`readiness_check_timeout_s=…`,
  `smoke_timeout_s=…`) with the spec defaults (<1s normal / <5s degraded / <10s smoke).
- **Migrations**: Alembic revision `0001_liveness_completion` creates the table; applied at bring-up
  (`alembic upgrade head`) per FR-008. Never edited once applied.
- **Frontend**: minimal Vite + React + TypeScript page that fetches `/health` on load, renders the
  overall verdict + per-subsystem breakdown, and shows an "unavailable/unknown" state on fetch failure
  (FR-010/011). Auto-refresh optional (a manual refresh button + optional 5s poll).

## Resolved unknowns

All Technical Context items are resolved. R1 (Python 3.13) and the RabbitMQ-in-tests question are
confirmed (2026-06-20); the constitution (v1.2.0) now mandates Testcontainers for Postgres + RabbitMQ.
The smoke CLI exits non-zero on failure for CI gating (see contracts/smoke-check-cli.md); the in-test
worker fixture starts both `cpu` and `io` pools.
