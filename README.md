# Notification Service — System Liveness Walking Skeleton

The thinnest end-to-end vertical that proves every subsystem (API, database, background
processing, frontend, local dev, CI/CD) is wired together and alive. See
[`specs/001-system-liveness/`](specs/001-system-liveness/) for the spec, plan, and tasks, and
[`.specify/memory/constitution.md`](.specify/memory/constitution.md) for the design rules.

## Health surfaces

| Endpoint | Semantics | Status |
|----------|-----------|--------|
| `GET /livez` | Liveness — process only (never DB/broker/workers) | 200 |
| `GET /readyz` | Readiness — process + DB (`SELECT 1`) | 200 / 503 |
| `GET /health` | Aggregate — DB + broker + a worker ping per pool | 200 / 503 + body |

`/livez` and `/readyz` are the Kubernetes probes and are **never** gated on workers, so a worker
outage cannot crash-loop or depool the API. The deep queue→pool round-trip (a real no-op task per
pool → sync-write completion row → async-read) is a **separate on-demand smoke check**
(`uv run --project backend smoke-check`), not part of `/health`.

## Run it

```bash
scripts/up-dev.sh   # Windows: ./up-dev.ps1  — builds images + brings the full stack up on kind
```

This builds the multi-stage images, ensures a local **kind** cluster with ingress-nginx, and applies
the dev overlay (api + cpu worker + io worker + postgres + rabbitmq + frontend). Migrations run once
per deploy in a `migrate-<tag>` Job — the API waits for the schema before serving. The frontend
renders `/health` at http://app.localhost. See
[`specs/002-env-up-scripts/quickstart.md`](specs/002-env-up-scripts/quickstart.md) for the bring-up
and validation guide, [`specs/001-system-liveness/quickstart.md`](specs/001-system-liveness/quickstart.md)
for the health-surface walkthrough, and [CLAUDE.md](CLAUDE.md) for day-to-day commands.

## Notification domain (003)

On top of the skeleton, feature
[`003-notification-management`](specs/003-notification-management/) adds the real product surface
(see its [quickstart](specs/003-notification-management/quickstart.md) for an end-to-end walkthrough):

- **Auth (US1)** — register → email-verify → login (PyJWT access token) → password reset. Passwords
  are hashed with **argon2**; every product endpoint is token-gated and ownership-scoped. Auth mail
  is awaited from the request path (aiosmtplib), never queued; in dev it lands in **Mailpit**.
- **Contacts (US4)** — a per-user contacts book (name + optional email/phone/device-token) that
  supplies template recipients.
- **Templates (US2)** — per-user template CRUD over a single channel (Email/SMS/Push) with
  channel-specific validation at save (e.g. SMS ≤160). Creating or editing a template **never sends**.
- **Sending (US3)** — `POST /templates/{id}/send` snapshots a **Dispatch** (decoupled from the
  template) and returns **202 in <1s**; the **io** worker fans out one resilient delivery per
  recipient (`queued → sent → delivered | failed`). Resilience lives in `application/`, **not** the
  channel adapters: **tenacity** retry/backoff, a per-channel/destination **pybreaker** circuit
  breaker, and a **hand-rolled idempotency** claim that guarantees no recipient is delivered twice.
  Channels talk to an in-repo **simulated provider** (`app.provider_sim`, its own workload) that
  injects latency/429/timeout/error and drives **asynchronous confirmation** — a **webhook** to
  `/api/v1/webhooks/delivery` for email/push, and a bounded **poll** task for SMS.

Adding a channel = one new adapter under `adapters/channels/<name>/` implementing `ChannelPort` plus
one binding in `bootstrap.py`; the shared dispatch/resilience core imports no concrete channel
(Open/Closed — constitution Principle II, enforced by `tests/unit/test_channel_registry.py`).

## Process model

**One uvicorn process per pod**, everywhere — there is no multi-worker process manager layered on
top. In prod, Kubernetes scales the API by **replica count** (one uvicorn per pod). The Celery
**cpu** (prefork) and **io** (threads) workers are their own separate processes/services in every
environment, orthogonal to the API process model.

## Why Celery (and not ARQ / TaskIQ)

This service is async-first (FastAPI + asyncpg). For a **fully-async** service, **ARQ** or **TaskIQ**
would be preferable — they have no synchronous seam, so workers could share the async stack directly.

**Celery is a deliberate choice here** because this project demonstrates a **mixed CPU + I/O
workload**: I/O-bound channel sends *and* a CPU-bound usage-aggregation job. Celery's mature
multi-pool model fits that directly — a **prefork** pool for CPU-bound work and a **threads** pool for
I/O-bound work — alongside its broad ecosystem (routing, monitoring, Flower). The cost is a
**synchronous seam**: Celery tasks use a separate synchronous SQLAlchemy engine (**psycopg v3**),
never the API's async **asyncpg** engine. Table models are shared; engines and sessions are not.

### I/O pool: threads (gevent + psycogreen as the higher-concurrency alternative)

The I/O pool uses `--pool=threads`: psycopg v3 is natively thread-safe, so no green-threading
monkey-patching is needed, and the realistic fan-out does not justify gevent. For much higher I/O
concurrency, a **gevent** pool with **psycogreen** (`psycogreen.gevent.patch_psycopg()`) is the
documented alternative — at the cost of monkey-patching and the associated debugging caveats.

## Layout

`backend/` — FastAPI (hexagonal: `domain/` → `ports/` → `application/`, with `adapters/`, `infra/`,
`api/`, `tasks/`, `cli/`). `frontend/` — React + Vite (multi-stage → nginx). `deploy/k8s/` — Kustomize
`base` + `overlays/{dev,prod}` (API, cpu/io workers, frontend, migrate Job, Ingress) with the
liveness/readiness probes wired; `scripts/` + root `up-*.ps1` — the bring-up entrypoints.
`.github/workflows/` — CI (ruff, mypy, pytest + Testcontainers, Coveralls) and CD (manifest
validation + deploy).
