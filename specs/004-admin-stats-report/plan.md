# Implementation Plan: Admin Account & Server-Wide Stats-Report

**Branch**: `004-admin-stats-report` | **Date**: 2026-06-22 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/004-admin-stats-report/spec.md`

## Summary

This feature finally exercises the constitution's **canonical CPU-bound usage-aggregation task** (deferred
by 003) and adds the project's first **admin-facing, application-defined notification type**. It is
backend-only (no frontend), delivered through the API + background workers:

- **Admin account** — exactly one default administrator provisioned by an idempotent **Alembic data
  migration** that reads credentials from `pydantic-settings`/env (a dev-only `admin@localhost`/`admin`
  placeholder, **refused outside dev** by a settings validator — mirroring the existing
  `_PLACEHOLDER_JWT_SECRET` pattern). The admin is pre-verified, unique, and `is_admin`-flagged. No
  promote/demote endpoints (out of scope). The admin keeps every ordinary capability and gains **no
  cross-user data access**.
- **Stats-report frequency** — one server-wide, persisted interval (integer **seconds**): default
  **2,592,000 (30 d)**, minimum **86,400 (24 h)**, `0` disables; values in 1–86,399 rejected. Admin-only
  `GET`/`POST /api/v1/admin/stats-report/frequency`. Changing it **resets the scheduling anchor**.
- **Scheduled reports** — **Celery Beat** fires a lightweight **due-check tick** every 60 s; when
  `now ≥ anchor + interval` the tick runs the **CPU-bound cycle on the prefork (`cpu`) pool**: one SQL
  `GROUP BY (user, UTC-hour)` pass → render a **24-bar PNG per scope with matplotlib (Agg)** → fan each
  out as an **independent resilient email on the threads (`io`) pool**. Every account gets a personal
  graph (all-zero if it never sent); the admin additionally gets a **global** graph.
- **Report email path** — a **new report-email `ChannelPort` adapter** (`Channel.REPORT`, real `smtplib`,
  attaching the PNG; the seed of the future *real* email channel), dev → Mailpit. It **reuses the existing
  resilient delivery pipeline** — retry/backoff + per-destination circuit breaker + idempotency + the
  persisted `queued → sent → delivered | failed` lifecycle (a report rests at `sent`, as SMTP returns no
  delivery receipt). Reports are **server-originated** (`dispatch.user_id` null), so they are **excluded**
  from every aggregation (`user_id IS NOT NULL`) and from every user's send-history. **No edits** to
  existing channel adapters; the only shared-flow change is a **one-time attachment capability** added to
  `Payload` + the delivery flow (an in-scope capability extension, not a per-channel edit — SC-010).
- **Seeding** — a standalone `backend/scripts/seed.py` that **COPY-bulk-inserts** ≈1,000 accounts and
  ≈500,000 completed sends (`dispatch` + `delivery` + a `sent` `delivery_transition`) spread across all
  24 UTC hours and many dates, bypassing the live send/resilience pipeline.

All stack/architecture choices are fixed by the constitution and the spec's ten Clarifications (Session
2026-06-22). The five plan-level forks the spec deferred were resolved with the user on 2026-06-22 and are
recorded under [Resolved Plan Decisions](#resolved-plan-decisions) and in [research.md](./research.md).

## Technical Context

**Language/Version**: Python **3.13** (`requires-python = ">=3.13"`, single-version CI). No frontend work.

**Primary Dependencies**: Inherited — FastAPI, uvicorn (uvloop + httptools), SQLAlchemy 2.0, asyncpg (API
engine), psycopg v3 (worker engine), Pydantic v2 + pydantic-settings, Alembic, Celery + RabbitMQ, PyJWT,
argon2-cffi, aiosmtplib, tenacity, pybreaker, structlog/OpenTelemetry/Sentry. **New for 004**:
`matplotlib` (headless **Agg** backend — renders the 24-bar PNG in the prefork worker; the only new
runtime dependency). **Celery Beat** is part of Celery (no new dependency — a `celery beat` process with a
static 60 s tick; the actual cadence lives in the DB). Report SMTP uses **stdlib `smtplib`** on the sync
io worker (no new dependency); `aiosmtplib` stays the async auth-email path.

**Storage**: PostgreSQL. New Alembic revision **`0003_admin_and_stats`** adds: `user_account.is_admin`
(boolean), a singleton **`stats_report_config`** table (`interval_seconds`, `anchor_at`), seeds the config
row (30 d, enabled) and the **admin row** (from settings, argon2-hashed, pre-verified, `is_admin=true`,
`ON CONFLICT DO NOTHING`). It also extends `dispatch` for **server-originated** report sends — **`user_id`
made nullable** (null ⇒ server-owned), a nullable **`attachment_png`** column for the graph, and
**`ck_dispatch_channel` widened to include `'report'`**. Reports reuse the existing
`dispatch`/`delivery`/`delivery_transition` tables (no report-specific table); the per-hour aggregate is
**not** persisted (computed on the fly). Shared ORM models; API writes via asyncpg, workers via the sync
psycopg engine.

**Testing**: pytest + pytest-asyncio. **Unit**: stats-config domain validation (`0` disables, `≥86,400`
accepted, `1–86,399` rejected, anchor reset / `next_run` math), histogram bucketing, the matplotlib
renderer (returns a non-empty PNG). **Integration** (real Postgres + RabbitMQ via Testcontainers): admin
login + frequency endpoint authz/validation; a full **report cycle driven by real `cpu` + `io` workers**
asserting per-scope 24-bucket correctness, zero-send all-zero graph, admin's two reports, global = sum,
never-`sent` excluded, no-recursion, and that report sends are persisted as **server-owned** rows absent
from user send-history; seeding correctness at reduced N. The report channel's SMTP is captured by a
**local `aiosmtpd` sink** reachable by the worker subprocess in round-trip tests (real external SMTP is
never hit). **Resilience** of the report email (retry/backoff → breaker → isolate-and-continue, persisted
`queued→failed`) is exercised **in-process** by injecting a **failing report `ChannelPort`** into
`DeliveryService`, exactly like the existing channel-resilience tests. Worker-subprocess rows isolated by **truncation**; API/in-process tests by
transaction-rollback.

**Target Platform**: Linux containers. Dev: local **kind** cluster via `scripts/up-dev.sh` / `up-dev.ps1`
at `http://app.localhost` (002). Prod: Kubernetes single-uvicorn pods. New in-cluster workload: a
**`beat`** Deployment (**replicas = 1** — exactly one scheduler). The **`cpu` (prefork) worker**, idle
since the skeleton, now does real work. Report email in dev → the existing **Mailpit** catcher.

**Project Type**: Web application (monorepo: `backend/` + `frontend/`); this feature is backend-only.

**Performance Goals** (from Success Criteria): the aggregation + render completes over the full ≈500,000
records and yields correct per-hour totals for both personal and global scopes (SC-007); frequency
read/write is an ordinary sub-second admin request.

**Constraints**: Async-all-the-way in the API — the frequency endpoints use asyncpg; **all CPU work
(aggregation + matplotlib render) runs on the prefork `cpu` pool**, all email I/O on the threads `io`
pool, never in the event loop. Workers use the **sync psycopg v3** engine, never asyncpg. The report
email path adds **one new channel adapter** with **no edits to existing channel adapters**; the only
shared-flow change is the one-time attachment capability (SC-010). Report sends are **persisted** (reusing
the resilient `dispatch`/`delivery` lifecycle) but **server-originated**, so excluded from every
aggregation via `user_id IS NOT NULL` (no recursion, SC-009). Admin credentials only via env (dev
placeholder refused outside dev). Ship the Alembic revision in this PR; never edit an applied migration.

**Scale/Scope**: Portfolio scope — 1 new column + 1 new singleton table (1 migration), 1 new API router
(admin frequency), 1 new port (`GraphRenderer`) + a `Payload` attachment extension + a new
`Channel.REPORT`, repo methods (async/sync stats config, sync aggregation/account-listing, sync report
dispatch/delivery create), 2 new adapters (report-email `ChannelPort` via `smtplib`, matplotlib renderer),
1 new Celery task (cpu `stats_report_tick`, reusing the existing `io` `deliver` task) + a Beat schedule, 1
standalone seed script, 1 new `beat` Deployment. Aggregation dataset ≈500K rows across ≈1,000 users.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| # | Principle | Status | How this plan complies |
|---|-----------|--------|------------------------|
| I | Code Quality (typed, linted, observable, pinned) | ✅ PASS | ruff + mypy (strict) via pre-commit & CI; `structlog`/OTel spans on the tick, cycle, render, and email tasks; Sentry on unhandled task errors; config (admin creds, report-from, due-check interval) via `pydantic-settings` — no `os.environ`; **matplotlib pinned** in `pyproject.toml`/`uv.lock`; multi-stage pinned image reused for the new `beat` process. |
| II | Architecture (hexagonal, proportionate, open/closed) | ✅ PASS | New domain (`StatsReportConfig`, `HourHistogram`) is pure (no FastAPI/SQLAlchemy/Celery/matplotlib). New **port** `GraphRenderer` + async/sync `StatsConfigRepository`/`SyncReportAggregationRepository`; matplotlib & SMTP live in **adapters**. **SC-010**: the report email is **one new `ChannelPort` adapter** (`Channel.REPORT`) — **no** edits to existing channel adapters. Adding **attachments** is a deliberate **one-time capability extension** of the shared `Payload`/delivery flow (every future channel benefits) — not the per-channel edit Open/Closed forbids. |
| III | Background Processing (Celery, mixed workload, sync seam) | ✅ PASS | **This feature realizes the constitution's canonical CPU task**: per-UTC-hour bucketing + bar-graph render on the **prefork `cpu`** pool; resilient report email on the **threads `io`** pool. Workers use the **sync psycopg v3** engine + `sync_repo` (aggregation, config); the API uses asyncpg. Beat publishes a static tick; due-ness is DB-driven. |
| IV | Resilience (first-class) | ✅ PASS | Report emails now use the **full** resilience model — the persisted `queued→sent→delivered\|failed` lifecycle + per-destination circuit breaker + idempotency keys — by **reusing the existing delivery pipeline** (a report rests at `sent`, as direct SMTP returns no delivery receipt). No deviation; nothing logged in Complexity Tracking. |
| V | Testing (real Postgres + broker, mocked HTTP, non-negotiable) | ✅ PASS | Integration on real Postgres + RabbitMQ (Testcontainers); the report cycle is driven by **real `cpu` + `io` workers**; the report channel's SMTP is **captured by a local `aiosmtpd` sink** reachable by the worker subprocess (an in-process mock can't patch a worker subprocess — 003's documented seam), with resilience tested in-process via an **injected failing report `ChannelPort`**. Worker rows cleaned by truncation; API/in-process by rollback; coverage → Coveralls. |
| VI | Security (tokens, hashing, secrets) | ✅ PASS | Admin credentials **only via env**; the committed default is a **dev-only placeholder refused outside dev** (validator mirrors `_PLACEHOLDER_JWT_SECRET`) — nothing secret is committed (FR-002). Admin password argon2-hashed in the data migration; OAuth2 + PyJWT reused; `/admin/*` requires the `is_admin` flag (authenticated non-admin → **403**, missing/invalid token → **401**). |
| VII | Operations (Docker, GH Actions, Kubernetes) | ✅ PASS | New **`beat` Deployment (replicas = 1)** reuses the multi-stage pinned image (different command); the **`cpu` worker** (already deployed) now does real work; schema + admin seed ship as Alembic **`0003`** run by the existing migrate Job (no API-start migration); admin creds via the k8s secret; report SMTP → Mailpit (dev). CI/CD on GitHub Actions. |

**Deliberate stack breadth** (observability, Celery two-pool model, CI/CD) is retained per the constitution
and is **not** logged as complexity. With reports now on the full resilience model, there are **no**
Principle-IV deviations to log.

## Project Structure

### Documentation (this feature)

```text
specs/004-admin-stats-report/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions & rationale
├── data-model.md        # Phase 1 — entities, config singleton, aggregation query, lifecycle reuse
├── quickstart.md        # Phase 1 — bring-up, seed, drive-a-cycle, per-user-story validation
├── contracts/           # Phase 1
│   ├── admin-stats-api.yaml   # OpenAPI: GET/POST /admin/stats-report/frequency
│   └── internal-ports.md      # report ChannelPort + Payload attachment, GraphRenderer, StatsConfig/aggregation repos, task contracts
└── tasks.md             # Phase 2 — /speckit-tasks (NOT created here)
```

### Source Code (repository root)

```text
backend/
  app/
    domain/
      stats.py               # NEW: StatsReportConfig (interval/anchor + validation, is_enabled,
                             #   next_run_at), HourHistogram (24 buckets), ReportScope — pure
      accounts.py            # (extend) add is_admin: bool to UserAccount
      channels.py            # (extend) add Channel.REPORT
      dispatch.py            # (extend) Dispatch gains optional attachment (threaded into Payload)
    ports/
      channels.py            # (extend) Payload gains optional attachment (image bytes + name)
      graph.py               # NEW: GraphRenderer — render_hour_histogram(counts, title) -> PNG bytes
      repositories.py        # (extend) Async/Sync StatsConfigRepository; SyncReportAggregationRepository;
                             #   sync report dispatch/delivery create
    application/
      stats_config.py        # NEW: StatsConfigService (async) — get/set frequency (validation, anchor reset)
      reporting.py           # NEW: ReportCycleService (sync) — aggregate → render → persist server-owned
                             #   dispatch/delivery → enqueue existing `deliver`; due-check + anchor advance
      delivery.py            # (extend) thread dispatch.attachment into Payload (one-time attachment support)
    adapters/
      mailer/
        smtp.py              # (reuse) async auth Mailer — UNCHANGED
      channels/
        report_email/        # NEW: SmtpReportEmailChannel (ChannelPort, sync stdlib smtplib, PNG attach)
      graphing/
        matplotlib_renderer.py # NEW: MatplotlibGraphRenderer (Agg) — GraphRenderer impl
      persistence/
        models.py            # (extend) is_admin; StatsReportConfig (singleton); dispatch.user_id nullable + attachment_png + 'report' channel
        async_repo.py        # (extend) AsyncStatsConfigRepository; account is_admin read
        sync_repo.py         # (extend) SyncStatsConfigRepository; SyncReportAggregationRepository (user_id IS NOT NULL); report dispatch/delivery create
    api/
      deps.py                # (extend) current_admin dependency (load account, require is_admin → 403)
      schemas.py             # (extend) FrequencyResponse, FrequencyUpdate
      routers/
        admin.py             # NEW: GET/POST /api/v1/admin/stats-report/frequency
    tasks/
      celery_app.py          # (extend) include app.tasks.reporting; beat_schedule (tick every 60 s)
      reporting.py           # NEW: stats_report_tick (cpu) → enqueues app.tasks.sending.deliver (io)
      deps.py                # (extend) WorkerContainer: stats config + aggregation repos, renderer, report cycle; report channel in registry
    bootstrap.py             # (extend) async stats config repo + StatsConfigService; admin lookup; bind Channel.REPORT adapter in the registry
    settings.py              # (extend) admin_email/admin_password (+ validator), report_mail_from, due-check interval
  migrations/versions/
    0003_admin_and_stats.py  # is_admin + stats_report_config (+seed) + seed admin + dispatch(user_id nullable, attachment_png, 'report' channel)
  scripts/
    seed.py                  # NEW: standalone COPY-based seeder (~1,000 accounts, ~500K completed sends)
  tests/
    unit/                    # stats-config validation; histogram bucketing; matplotlib renderer smoke
    integration/
      test_admin_frequency.py  # seeded-admin login; GET default; POST valid/invalid/disable; 403/401
      test_report_cycle.py     # real cpu+io workers: per-scope buckets, zero-user, admin x2, global=sum, no-recursion
      test_seed.py             # reduced-N seed → counts/distribution match; cycle totals match seed
      test_report_resilience.py# in-process: failing report ChannelPort → recipient isolated (queued→failed), cycle continues
    factories/               # (extend) admin/account + completed-send factories
    conftest.py              # (extend) admin client; cpu+io worker / beat-tick trigger; aiosmtpd SMTP sink; failing report channel
  pyproject.toml             # (extend) add matplotlib (pinned); aiosmtpd (test SMTP sink)
frontend/                    # unchanged (UI out of scope)
deploy/k8s/
  base/
    beat.yaml                # NEW: Celery Beat Deployment (replicas=1) — same image, `celery ... beat`
    cpu-worker.yaml          # (reuse) now actually does work
    kustomization.yaml       # (extend) add beat.yaml
  overlays/dev/              # (extend) admin creds in secret.env; report SMTP → Mailpit; report_mail_from
  overlays/prod/             # (extend) admin creds required via secret (placeholder refused outside dev)
```

**Structure Decision**: Web-application hexagonal layout per CLAUDE.md, dependencies pointing inward to
`domain/`. New domain rules → `domain/stats.py`; orchestration → `application/` (`stats_config.py` async
for the API, `reporting.py` sync for the worker cycle); all framework/I/O (matplotlib, SMTP, SQL
aggregation) → `adapters/` behind new ports; HTTP surface → `api/routers/admin.py`; background entrypoints
→ `tasks/reporting.py` (thin — delegate into `application/reporting.py`). The report email is added as
**one new `ChannelPort` adapter** (`Channel.REPORT`, sync SMTP) bound in the registry and run through the
**existing resilient delivery pipeline**; the only shared-flow change is a one-time attachment capability on
`Payload`/`DeliveryService` (SC-010). It is intentionally the seed of the future **real** email channel.

## Resolved Plan Decisions

The spec deferred these to planning; resolved with the user 2026-06-22 (details + alternatives in
[research.md](./research.md)).

1. **Report email path** — a **new report-email `ChannelPort` adapter** (`Channel.REPORT`,
   `adapters/channels/report_email/`, stdlib `smtplib`, PNG attached), **not** the existing
   `simulatedEmail` channel (which is HTTP→`provider_sim`). Reports run through the **existing resilient
   delivery pipeline** (retry/backoff + breaker + idempotency + the persisted `queued→sent→…` lifecycle) and
   are **server-originated** (`dispatch.user_id` null ⇒ excluded from aggregation + user history). The PNG
   rides as an **attachment** via a one-time extension of the shared `Payload`/delivery flow (channels can
   now carry attachments — an in-scope capability add, not a per-channel edit). It is the seed of the future
   real email channel; dev → Mailpit. **No adapter-level failure injection**; resilience is proven by
   injecting a failing report `ChannelPort` into `DeliveryService` in tests.
2. **Admin provisioning** — an idempotent **Alembic data migration** (`0003`) seeds the admin, reading
   `admin_email`/`admin_password` from `settings` (env) with a **dev-only `admin@localhost`/`admin`
   placeholder refused outside dev** (validator mirrors `_PLACEHOLDER_JWT_SECRET`). GitLab-style UX —
   dev works out of the box; prod fails fast until real creds are set — while honoring FR-002 (no
   committed secret) and the constitution's "migrations as a one-shot Job" rule.
3. **Hour-bucket source** — derive the UTC hour from the **existing `delivery_transition` row with
   `to_status='sent'`** (`EXTRACT(HOUR FROM at AT TIME ZONE 'UTC')`). **No** denormalized `sent_at`
   column — reuse the append-only truth (single source). Seeding writes the matching `sent` transition
   rows with explicit `at` timestamps.
4. **Scheduling** — **Celery Beat** (new `beat` Deployment, replicas = 1) fires a static
   `stats_report_tick` every **60 s**; the tick reads `stats_report_config`, and when
   `now ≥ anchor_at + interval_seconds` (and `interval_seconds ≠ 0`) runs the cycle on the `cpu` pool and
   advances `anchor_at`. A frequency `POST` resets `anchor_at = now()`, so the next report fires one full
   interval after the change. DB-anchored due-ness (not a static crontab) supports arbitrary intervals.
5. **Graphing** — **matplotlib** with the headless **Agg** backend renders a 24-bar PNG (one bar per UTC
   hour 00–23); the PNG is **attached** to the email. Rendering happens on the **prefork `cpu`** pool
   (genuinely CPU-bound at ~1,001 graphs/cycle).

## Complexity Tracking

> **None.** Report emails now use the full persisted-lifecycle + breaker + idempotency model (by reusing
> the existing delivery pipeline), so the earlier Principle-IV deviation is gone. Adding **attachment**
> support edits the shared `Payload`/`DeliveryService`, but that is a deliberate **capability extension**
> (channels can now carry attachments) — not the per-channel edit Open/Closed forbids — so it is **not** a
> logged deviation either. The broad stack and the new `beat`/active-`cpu` workloads are deliberate and
> per-constitution — **not** product complexity — so nothing is logged here.

## Phase Outputs

- **Phase 0** → [research.md](./research.md): the five resolved forks (report-email **channel reusing the
  delivery pipeline**, admin-via-migration with placeholder refusal, transition-derived hour bucket, Celery
  Beat due-check, matplotlib/Agg), plus the cpu-aggregate-then-io-deliver split, server-originated
  exclusion, beat-singleton, and the SMTP-sink test seam — each with rationale + alternatives.
- **Phase 1** → [data-model.md](./data-model.md), [contracts/](./contracts/),
  [quickstart.md](./quickstart.md); agent context (`CLAUDE.md` SPECKIT marker) updated to this plan.
- **Phase 2** → `/speckit-tasks` will generate `tasks.md` (not produced by this command).
```