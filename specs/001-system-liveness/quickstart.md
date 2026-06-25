# Quickstart & Validation: System Liveness Walking Skeleton

A runnable guide that proves the slice end-to-end. Commands follow CLAUDE.md. Implementation details
live in `tasks.md`/code, not here.

## Prerequisites

- Docker, `kind`, and `kubectl` for the dev cluster (plus Docker for Testcontainers), `uv`, Node/npm (frontend).
- Repo checked out on branch `001-system-liveness`.

## One-command bring-up (US2 / SC-001)

```bash
scripts/up-dev.sh          # Windows: ./up-dev.ps1 — builds images + brings the stack up on kind
```

Brings up api + cpu worker + io worker + postgres + rabbitmq + frontend on a local **kind** cluster.
Migrations run once per deploy in a `migrate-<tag>` Job (`alembic upgrade head`) so
`liveness_completion` exists (FR-008), and the API waits for the schema before serving. Expected:
every workload reaches Ready with no manual steps.

> Day-to-day one-offs run on the host with `uv run …` (or
> `kubectl -n notification exec deploy/notification-api -- …`). Migrations are a discrete step now
> (the `migrate-<tag>` Job), never the API start command.

## Validate the health surfaces (US1)

```bash
curl -i http://api.localhost/livez     # → 200 {"status":"alive"}          (process-only)
curl -i http://api.localhost/readyz    # → 200 {"status":"ready"}          (process + DB)
curl -s http://api.localhost/health | jq   # aggregate: status + per-subsystem breakdown (DB, broker, cpu, io)
```

**Failure-mode checks** (take a dependency down by scaling it to zero, e.g.
`kubectl -n notification scale deploy/postgres --replicas=0`; map to acceptance scenarios & SC-002/003/004/010):

| Action | `/livez` | `/readyz` | `/health` |
|--------|----------|-----------|-----------|
| Stop Postgres | 200 | **503** `not_ready` | **503**, `data_store` failing |
| Stop both workers | 200 | 200 | **503**, `worker_pool_cpu`+`worker_pool_io` failing |
| Stop RabbitMQ | 200 | 200 | **503**, `message_broker` (and worker pings) failing |

Key invariants: `/livez` stays 200 in all of the above (no restart loop); `/health` returns within
~5s even while a dependency is down and **never** blocks on a job.

## Validate the deep round-trip (US4 / FR-009 / SC-007)

```bash
kubectl -n notification exec deploy/notification-api -- python -m app.cli.smoke   # or on host: uv run smoke-check
echo $?    # 0 = both cpu+io completion rows appeared within the bound; 1 = timeout/failure
```

Proves: real task → real broker → real worker (prefork + threads) → **sync-write** completion row →
**async-read** confirmation, keyed by a per-run `correlation_id`. See
[contracts/smoke-check-cli.md](./contracts/smoke-check-cli.md).

## Validate the frontend (US3 / SC-006)

Open the frontend at **http://app.localhost** and confirm the page renders the overall verdict +
per-subsystem breakdown from `/health`. Scale Postgres to zero → the page reflects non-healthy;
scale the API to zero → the page shows "unavailable/unknown" (not blank, not false-healthy).

## Quality gate (US4 / SC-008 / SC-009)

```bash
uv run pytest                                   # real Postgres + RabbitMQ via Testcontainers (run on host/CI)
uv run ruff check . && uv run ruff format --check .
uv run mypy .
```

- Telemetry assertions (FR-017/SC-009) run inside the suite: structured startup log line, a trace span
  on a `/health` request, and Sentry client initialization.
- Run `pytest` on the **host** (or CI), never inside a compose container — Testcontainers needs the
  Docker daemon.

## Acceptance traceability

| Spec item | Validated by |
|-----------|--------------|
| US1 (aggregate + probes) | curl table above; `test_livez_readyz.py`, `test_health_aggregate.py` |
| US2 (one-command bring-up + migration) | `scripts/up-dev.sh`; `migrate-<tag>` Job applied |
| US3 (frontend) | frontend manual check |
| US4 (gate + smoke) | `pytest`, ruff, mypy; `app.cli.smoke`; `test_smoke_roundtrip.py` |
| FR-016/017 telemetry | `test_telemetry.py` |
