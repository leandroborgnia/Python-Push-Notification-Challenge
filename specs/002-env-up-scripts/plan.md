# Implementation Plan: Environment Bring-Up Scripts (up-dev / up-prod)

**Branch**: `002-env-up-scripts` | **Date**: 2026-06-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/002-env-up-scripts/spec.md`

## Summary

Replace feature 001's `docker compose` dev bring-up with a **Kubernetes-on-both-environments** flow,
delivered as four entrypoints: canonical bash scripts `scripts/up-dev.sh` / `scripts/up-prod.sh` and
thin PowerShell wrappers `up-dev.ps1` / `up-prod.ps1` that invoke them through `wsl.exe` (logic lives
in exactly one place → Windows/CI/container/prod parity). `up-dev` auto-creates a local **kind**
cluster (with the host port-mappings ingress-nginx needs), installs ingress-nginx (pinned to a released `controller-vX.Y.Z`), builds the app +
frontend images, `kind load`s them, and applies `kubectl kustomize deploy/k8s/overlays/dev`. `up-prod`
builds + pushes to a configured registry and applies the `prod` overlay against the existing
production context (never creating/destroying clusters). Manifests are organized with **Kustomize**
(`base` + `overlays/{dev,prod}`); the app image becomes a **multi-stage** build (build stage + the
existing `python:3.13.14-slim` pinned runtime, no build tools); the frontend ships as its own
multi-stage image (Node build → nginx). Schema migrations move out of the API start command into a
**one-shot per-deploy Job** (`migrate-<tag>`), with an API init container that blocks until the Job
completes — so replicas never race and migrations run exactly once per deploy.

All technology/architecture choices are fixed by the constitution (v1.5.0) and the spec's eight
Clarifications. This plan maps them onto concrete structure and does not re-decide them. Two
plan-level forks left open by the spec were escalated and resolved this session (see
[Decisions Resolved This Session](#decisions-resolved-this-session)); remaining plan-level defaults
are documented in [research.md](./research.md) and flagged under
[Flagged Underspecifications](#flagged-underspecifications).

## Decisions Resolved This Session

1. **Migration mechanism** (reconciles the "init container" clarification with SC-007's
   "once per deploy, never once-per-replica"): a **one-shot per-deploy Job** `migrate-<image-tag>`
   runs `alembic upgrade head`; the API Deployment keeps a lightweight **init container that only
   *waits*** until the schema is at head (it performs no DDL). The bring-up script additionally
   `kubectl wait --for=condition=complete job/migrate-<tag>` for fast feedback and a non-zero exit on
   failure. This satisfies SC-007 while honouring the "API does not serve until migrated" intent.
2. **Ingress routing**: **two hosts, no path rewrite.** Dev → `app.localhost` (frontend) +
   `api.localhost` (API); prod → configured hostnames via the prod overlay. The API keeps its
   top-level paths (`/livez`, `/readyz`, `/health`). The frontend image is built with
   `VITE_API_BASE_URL=http://api.localhost` in dev (overlay-configured for prod).

## Technical Context

**Language/Version**: **Bash** (POSIX sh-compatible, executed under WSL/Linux) for the canonical
scripts; **PowerShell** for the thin wrappers; **Kustomize**-flavoured Kubernetes YAML; multi-stage
**Dockerfiles**. The application itself (Python **3.13**, TypeScript/React) is unchanged by this
feature.

**Primary Dependencies** (tooling, not app deps): `kubectl` (with its built-in kustomize), `kind`,
Docker, `wsl.exe` (Windows side only); ingress-nginx (installed into kind by `up-dev`, pinned to a released `controller-vX.Y.Z`). Images: the
existing `python:3.13.14-slim` runtime + `ghcr.io/astral-sh/uv` build tool (already pinned by
digest), `node:18.20.8-alpine` build stage + an `nginx` runtime for the frontend, and pinned
`postgres:16.14-alpine` / `rabbitmq:4.3.2-management` for the dev datastores.

**Storage**: **dev** runs **in-cluster** Postgres 16.14 + RabbitMQ 4.3.2 as workloads (ephemeral —
`emptyDir`, acceptable per the spec assumptions). **prod** uses **managed/external** Postgres +
RabbitMQ supplied via a pre-existing `notification-secrets` Secret; `up-prod` fails fast if that
connection config is absent (no in-cluster datastore fallback).

**Testing**: this feature adds no application code, so it adds no pytest cases; it is validated by the
acceptance scenarios in [quickstart.md](./quickstart.md) (dev bring-up to Ready, idempotent re-run,
prod preflight failure, wrapper exit-code propagation, runtime image carries no `uv`, migrations once
per deploy, run-from-subdirectory, CRLF guard). Bash scripts SHOULD pass `shellcheck`. The existing
Testcontainers pytest suite is unaffected and still runs on the host/CI.

**Target Platform**: scripts execute on **Linux** (WSL on Windows, native on CI/teammates). Deploy
target is **Kubernetes** — a local **kind** cluster for dev, the existing production cluster for prod.

**Project Type**: Web application (monorepo: `backend/` + `frontend/`) plus repo-root ops tooling
(`scripts/`, `deploy/k8s/`, root wrappers).

**Performance Goals**: SC-005 — a missing prerequisite (no WSL / no cluster / failed build) produces a
clear error and a non-zero exit within **10 seconds** (fail fast, never hang). SC-006 — the runtime
image carries **no build toolchain** (`uv`/compilers absent — the authoritative check) and is
consequently smaller than a single-stage equivalent.

**Constraints**: bash scripts MUST be **LF** (enforced by `.gitattributes`) so a Windows checkout
runs under WSL; PowerShell wrappers carry **no orchestration logic** (only the `wsl.exe` call +
arg/exit-code passthrough); deploy uses **kubectl only** (no standalone `kustomize`/`helm` binary);
every apply is **declarative/idempotent**; the runtime image carries **no build tools**; migrations
run **once per deploy** (Job), never per replica; every script resolves the **repo root** regardless
of CWD and exits `0`/non-zero for automation.

**Scale/Scope**: 2 environments; 4 entrypoint scripts (+ a shared bash lib); a Kustomize `base` of
~7 workloads (API, cpu-worker, io-worker, frontend, their Services, the migrate Job, an Ingress) plus
a dev overlay that adds Postgres + RabbitMQ; reworks to `backend/Dockerfile`, `frontend/Dockerfile`,
and retirement of `docker-compose.yml`.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| # | Principle | Status | How this plan complies |
|---|-----------|--------|------------------------|
| I | Code Quality (typed, linted, **pinned & reproducible builds**) | ✅ PASS | No app code changes (typing/lint untouched). **Pinning**: every image stays pinned by patch + digest (slim runtime, uv, node, nginx, postgres, rabbitmq); the deployed app image is referenced by an **immutable per-run tag** (git-SHA based), never `latest` (FR-018); manifests reference that exact tag. |
| II | Architecture (hexagonal, proportionate, open/closed) | ✅ PASS | Pure ops/infra feature — no domain/application/adapters edits, no channel or dispatch-core changes. The hexagonal layout is preserved; the multi-stage image and manifests are packaging, not architecture. |
| III | Background Processing (Celery, mixed workload, sync seam) | ✅ PASS | The **cpu** (prefork) and **io** (threads) workers become their **own Deployments** with pool-identifying nodenames (`-n cpu@%h`, `-n io@%h`) — separate processes from the API in every environment, exactly as the constitution requires. Workers use the sync engine; no change to that seam. |
| IV | Resilience (first-class) | ✅ PASS (N/A) | No channel/resilience code touched; nothing removed or precluded. |
| V | Testing (real Postgres + broker, mocked HTTP, non-negotiable) | ✅ PASS | The pytest/Testcontainers suite is unchanged and still gates CI. This feature's scripts are validated by quickstart scenarios + `shellcheck`; Testcontainers (not the kind cluster) remains the test substrate. |
| VI | Security (tokens, hashing, **secrets**) | ✅ PASS | Secrets stay in env/Kubernetes Secrets, never hard-coded **and never committed**. **prod** consumes an externally-managed `notification-secrets` (managed DB/RabbitMQ URLs) and fails fast if absent; **dev** builds `notification-secrets` via a kustomize `secretGenerator` sourced from a **gitignored** `secret.env` that `up-dev` creates from a committed `secret.env.example` template — so no credential values land in git (Principle VI stays absolute). |
| VII | Operations (Docker, GitHub Actions, **Kubernetes**) | ✅ PASS | This feature *is* the constitution-v1.5.0 realization: **dev + prod both on Kubernetes**; single-process uvicorn per pod scaled by replicas; **multi-stage** images with a minimal pinned runtime; **migrations as a discrete step** (one-shot Job, never the API CMD). `docker compose` is retired as the dev orchestrator (FR-015). CI/CD on GitHub Actions is unaffected (pipeline internals out of scope). |

**Deliberate stack breadth** (observability, Celery/RabbitMQ, CI/CD) is retained and is **not** logged
as complexity. No gate violations → [Complexity Tracking](#complexity-tracking) is empty.

## Project Structure

### Documentation (this feature)

```text
specs/002-env-up-scripts/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions & rationale
├── data-model.md        # Phase 1 — deployment topology, config matrix, bring-up lifecycle
├── quickstart.md        # Phase 1 — bring-up & validation guide (acceptance scenarios → SCs)
├── contracts/           # Phase 1 — script CLI contract + kustomize-overlay contract
│   ├── scripts-cli.md
│   └── kustomize-overlays.md
└── tasks.md             # Phase 2 — /speckit.tasks (NOT created here)
```

### Source Code (repository root)

```text
up-dev.ps1                     # thin wrapper → wsl.exe bash ./scripts/up-dev.sh "$@"; exit $LASTEXITCODE
up-prod.ps1                    # thin wrapper → wsl.exe bash ./scripts/up-prod.sh "$@"; exit $LASTEXITCODE
.gitattributes                 # *.sh text eol=lf  (LF guaranteed even on Windows checkout)

scripts/
  lib/common.sh                # shared: repo-root resolution, logging, prereq checks, image-tag derivation
  up-dev.sh                    # kind ensure+create → ingress-nginx → build → kind load → render+apply dev overlay → wait
  up-prod.sh                   # preflight (context+secret) → build → push → render+apply prod overlay → wait

deploy/k8s/
  kind-config.yaml             # kind cluster config (control-plane: ingress-ready=true + host port-maps 80/443); used only by up-dev — NOT part of the kustomize tree
  base/
    kustomization.yaml         # references all base resources; images: placeholders (__API_IMAGE__/__FRONTEND_IMAGE__)
    namespace.yaml             # notification namespace
    api.yaml                   # API Deployment (initContainer await-migrations → uvicorn) + Service
    cpu-worker.yaml            # prefork worker Deployment (-n cpu@%h -Q cpu)
    io-worker.yaml             # threads worker Deployment (-n io@%h -Q io)
    frontend.yaml              # frontend Deployment (nginx) + Service
    migrate-job.yaml           # one-shot Job migrate-<tag> (DNS-valid name via tag substitution): alembic upgrade head
    ingress.yaml               # Ingress: app host → frontend, api host → API (hosts patched per overlay)
  overlays/
    dev/
      kustomization.yaml       # namespace, image-ref placeholders substituted by render_apply (__API_IMAGE__/__FRONTEND_IMAGE__), secretGenerator (from secret.env),
                               #   replicas=1, patches base ingress hosts → app.localhost / api.localhost
      secret.env.example       # committed template; up-dev copies → gitignored secret.env (no creds in git)
      postgres.yaml            # in-cluster Postgres Deployment + Service (emptyDir, pinned image)
      rabbitmq.yaml            # in-cluster RabbitMQ Deployment + Service (pinned image)
      rabbitmq-config.yaml     # ConfigMap of permit-deprecated.conf (moved from deploy/rabbitmq/)
    prod/
      kustomization.yaml       # image-ref placeholders substituted by render_apply (__API_IMAGE__/__FRONTEND_IMAGE__ → ${REGISTRY}/…:<sha>), replicas=N,
                               #   patches ingress hosts → configured prod hostnames; NO datastores, NO secret
      replicas-patch.yaml      # prod replica counts

backend/Dockerfile             # REWORKED: explicit multi-stage (build → slim runtime); CMD drops `alembic upgrade head`
frontend/Dockerfile            # REWORKED: multi-stage (node build → nginx serving static assets)
frontend/nginx.conf            # NEW: nginx config with SPA history-fallback (used by the runtime stage)

# Retired / updated by this feature
docker-compose.yml             # REMOVED (dev orchestrator retired — FR-015)
deploy/k8s/deployment.yaml     # FOLDED INTO base/api.yaml (001's flat manifest)
deploy/k8s/service.yaml        # FOLDED INTO base/api.yaml
deploy/rabbitmq/permit-deprecated.conf  # MOVED into overlays/dev/rabbitmq-config.yaml (ConfigMap)
CLAUDE.md / README.md / specs/001-system-liveness/quickstart.md  # compose references updated → k8s
```

**Structure Decision**: Web-application monorepo (unchanged) + repo-root ops tooling. Bash is the
single source of truth (`scripts/`), PowerShell wrappers at the root mirror the requested shape
(`up-dev.ps1` → `wsl.exe bash ./scripts/up-dev.sh`). Manifests follow the standard Kustomize
`base` + `overlays/{dev,prod}` layout so `dev`/`prod` differ only by overlay (images, replicas,
datastores, ingress hosts, secret source) — applied with kubectl's built-in kustomize, no extra
tooling.

## Flagged Underspecifications

Plan-level defaults chosen here and documented in [research.md](./research.md); flagged for
visibility, not blocking.

1. **Per-run image tag scheme** — **Decided:** derive from `git rev-parse --short HEAD`; dev tags as
   `dev-<sha>` and appends `-dirty-<epoch>` when the working tree is dirty (dev rebuilds frequently);
   prod uses the bare `<sha>` and requires a clean tree. Never `latest` (FR-018, Principle I).
2. **Injecting the per-run tag with kubectl-only** — **Decided:** manifests carry `__API_IMAGE__` /
   `__FRONTEND_IMAGE__` placeholders (in `image:` string fields) plus a **DNS-valid** token in the
   migrate Job `name` (so the un-substituted base still passes `kubeconform`); the script renders with
   `kubectl kustomize overlays/<env>`, substitutes the per-run values, and pipes to
   `kubectl apply -f -`. Equivalent to `kubectl apply -k` but lets an immutable tag flow in without a
   standalone `kustomize`/`helm` binary (honours FR-017's "no tooling beyond kubectl").
3. **API init-container wait mechanism** — **Decided:** the `await-migrations` init container reuses
   the app image and polls the DB until `alembic current` is at head (DB-only; no Kubernetes RBAC for
   the pod). The Job ordering/failure is surfaced by the script's `kubectl wait` on the Job.
4. **Dev datastore persistence** — **Decided:** `emptyDir` (ephemeral), per the spec assumption that
   local data loss is acceptable; swappable for a PVC later without changing the scripts.
5. **Worker health probes** — **Decided:** exec liveness probe `celery -A app.tasks.celery_app
   inspect ping -d <pool>@$(hostname)` per worker Deployment (no HTTP surface on workers).
6. **Prod ingress hostnames + registry** — supplied via the prod overlay / environment
   (`IMAGE_REGISTRY`, configured hosts); provisioning them is out of scope (spec Assumptions).

## Complexity Tracking

> No Constitution Check violations. The broad stack is deliberate per the constitution and is not a
> violation. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |

## Phase Outputs

- **Phase 0** → [research.md](./research.md): resolves the migration topology (Job + wait-init), the
  ingress two-host scheme, the kubectl-only image-tag injection, kind cluster auto-create + ingress
  port-mappings, the bash-canonical/thin-PS-wrapper convention + LF enforcement, multi-stage app +
  frontend image shapes, dev vs prod datastore/secret strategy, and idempotent declarative apply +
  rollout-wait.
- **Phase 1** → [data-model.md](./data-model.md) (resource inventory, per-env config matrix, bring-up
  lifecycle), [contracts/](./contracts/) (`scripts-cli.md`, `kustomize-overlays.md`),
  [quickstart.md](./quickstart.md); agent context (`CLAUDE.md` SPECKIT marker) updated to reference
  this plan.
- **Phase 2** → `/speckit.tasks` will generate `tasks.md` (not produced by this command).
