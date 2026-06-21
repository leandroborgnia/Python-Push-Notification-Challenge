# CLAUDE.md

Operating manual for working in this repo. **The design rules and non-negotiables live in
`.specify/memory/constitution.md` — read that first.** This file is about *how to work* here,
not what to build.

## What this is

A notification service with pluggable **Email / SMS / Push** channels. Async **FastAPI** backend,
**Celery** (RabbitMQ broker) for background channel sends (I/O-bound) and a CPU-bound usage-
aggregation job, **PostgreSQL**, and a **React** (Vite) frontend. Built with **Spec Kit**: features
flow through `/speckit.specify → .plan → .tasks → .implement`, and specs live under `specs/`.

## Repo structure (hexagonal — dependencies point inward toward `domain/`)

```text
backend/
  app/
    domain/                  # pure entities, value objects — NO SQLAlchemy, NO FastAPI
    ports/                   # ChannelPort, NotificationRepository, ... (Protocols)
    application/             # use cases + resilience: retry/backoff, circuit breaker,
                             #   idempotency, queued→sent→delivered/failed lifecycle
    adapters/                # ALL driven adapters
      channels/              #   email/ sms/ push/ — ChannelPort impls, simulate failure
      persistence/
        models.py            #   SQLAlchemy ORM models (shared by both engines, NOT domain entities)
        async_repo.py        #   AsyncSession repositories (API)
        sync_repo.py         #   sync Session repositories (Celery)
    infra/
      db/async_engine.py     #   create_async_engine (asyncpg) — API
      db/sync_engine.py      #   create_engine (psycopg) — Celery
      telemetry.py           #   structlog / OpenTelemetry / Sentry wiring
    api/                     # FastAPI routers, dependencies, Pydantic DTO schemas
    tasks/                   # Celery app + thin tasks that delegate into application/
    bootstrap.py             # composition root: bind ports -> adapters
    main.py                  # FastAPI instance (uvicorn target: app.main:app)
    settings.py              # pydantic-settings
  scripts/seed.py            # COPY-based demo seeding (the analytics dataset)
  migrations/                # Alembic env.py + versions/
  tests/{unit,integration,factories}/
frontend/                    # React + Vite app
```

## Commands

`scripts/up-dev.sh` (Windows: `./up-dev.ps1` → WSL) is the dev orchestration entrypoint — it builds
the images and brings the full stack (api + cpu worker + io worker + postgres + rabbitmq + frontend)
up on a local **kind** cluster, reachable at `http://app.localhost`. The uvicorn/celery lines below
are **service entrypoints** (baked into the multi-stage image and reused by the k8s manifests), *not*
daily hand-run commands. Day-to-day one-offs run on the host with `uv run …` (or
`kubectl -n notification exec deploy/notification-api -- …`).

| Purpose | Command |
|---|---|
| Dev bring-up (kind) | `scripts/up-dev.sh` · Windows: `./up-dev.ps1` |
| Prod bring-up | `IMAGE_REGISTRY=<registry> scripts/up-prod.sh` · Windows: `./up-prod.ps1` |
| Install deps | `uv sync` |
| API (dev) | `uv run uvicorn app.main:app --reload --port 8000` |
| API (prod, per pod) | `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| Validate k8s manifests | `kubectl kustomize deploy/k8s/overlays/<env> \| kubeconform -strict -summary -` |
| Celery CPU worker (prefork) | `uv run celery -A app.tasks.celery_app worker --pool=prefork -n cpu@%h -Q cpu -c 4` |
| Celery I/O worker (threads) | `uv run celery -A app.tasks.celery_app worker --pool=threads -n io@%h -Q io -c 20` |
| New migration | `uv run alembic revision --autogenerate -m "msg"` |
| Apply migrations | `uv run alembic upgrade head` |
| Single test | `uv run pytest tests/integration/test_x.py::test_case` |
| Full suite | `uv run pytest` |
| Lint + format | `uv run ruff check --fix . && uv run ruff format .` |
| Typecheck | `uv run mypy .` |
| Pre-commit (all files) | `uv run pre-commit run --all-files` |
| Frontend (dev / build) | `npm run dev` / `npm run build` (in `frontend/`) |

> Run `pytest` on the **host** (or in CI), never inside a cluster pod — Testcontainers needs
> access to the Docker daemon to spin up its own ephemeral Postgres and RabbitMQ.

## Environments

- **dev** — a local **kind** cluster brought up by `scripts/up-dev.sh` / `up-dev.ps1` (constitution
  v1.5.0, feature `002-env-up-scripts`): multi-stage images, in-cluster Postgres + RabbitMQ, and a
  one-shot `migrate-<tag>` Job (the API has an init container that waits until the schema is at head).
  App at `http://app.localhost`. `docker compose` was retired by 002.
- **test** — ephemeral Testcontainers Postgres, created per test run. Not a deployed environment.
- **prod** — Kubernetes: single-uvicorn pods scaled by replica count.
- **API process model**: single-process uvicorn everywhere; in prod, Kubernetes scales it by replica
  count (one uvicorn process per pod) — no multi-worker process manager layered on top.
- **Celery workers are their own processes/services in every environment** — orthogonal to the API
  process model. The cpu (prefork) and io (threads) workers are always separate from the API.

## Conventions

- **Add a notification channel**: create a new adapter under `adapters/channels/<name>/` implementing
  `ChannelPort`, then bind it in `bootstrap.py`. **Do not edit existing channel adapters** or the
  dispatch core (Open/Closed — see constitution Principle II).
- **Where new code goes**: domain rules → `domain/`; orchestration/resilience → `application/`;
  anything touching I/O or a framework → `adapters/` or `infra/`; HTTP surface → `api/`; background
  entrypoints → `tasks/` (keep them thin, delegate into `application/`).
- **Branches / commits / PRs**: work on Spec Kit feature branches (`NNN-feature-name`); Conventional
  Commits (`feat:`, `fix:`, `docs:`…). A PR must pass the plan's Constitution Check plus CI (ruff,
  mypy, pytest, coverage). Ship Alembic revisions in the **same PR** as the model change.

## Gotchas (read these)

- **Async all the way.** No sync or blocking calls inside the API event loop — use async drivers and
  `await`. Offload blocking/CPU work to Celery.
- **Celery uses the SYNCHRONOUS engine (psycopg), NEVER the async asyncpg engine.** This is the #1
  footgun. ORM models are shared; engines and sessions are not. API → `async_engine.py`/`async_repo.py`;
  Celery → `sync_engine.py`/`sync_repo.py`.
- **Route by workload**: CPU-bound tasks → `cpu` queue (prefork pool); I/O-bound sends → `io` queue
  (threads pool). psycopg3 works with threads natively, no monkey-patching. Start workers with
  pool-identifying nodenames (`-n cpu@%h`, `-n io@%h`) so the readiness check can ping a worker per pool.
- **Adapters simulate failure on purpose** (latency, random errors, 429s). The resilience logic
  (retry/backoff, circuit breaker, idempotency) lives in `application/`, **not** in the adapters.
- **Never edit an applied migration — add a new one.**
- **Secrets come from pydantic-settings / env, never hard-coded.**

Follow the constitution at `.specify/memory/constitution.md` for anything not covered here.

<!-- SPECKIT START -->
Active feature: **002-env-up-scripts**. For technologies, project structure, shell commands, and
other important context, read the current plan: `specs/002-env-up-scripts/plan.md` (with
`spec.md`, `research.md`, `data-model.md`, `contracts/`, and `quickstart.md` alongside it).
<!-- SPECKIT END -->
