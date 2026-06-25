# Phase 1 Data Model: Environment Bring-Up

This feature ships no application entities (no new tables/DTOs). Its "data model" is the **deployment
topology**: the Kubernetes resource inventory each environment renders, the per-environment
configuration matrix, and the bring-up lifecycle (state transitions). Field/validation rules are
derived from the spec's Functional Requirements.

## A. Kustomize resource inventory

Rendered by `kubectl kustomize deploy/k8s/overlays/<env>`. **B** = in `base` (both envs);
**dev** / **prod** = overlay-only.

| Resource | Kind | Scope | Notes |
|---|---|---|---|
| `notification` | Namespace | B | All resources land here. |
| `notification-api` | Deployment | B | `await-migrations` init container → `uvicorn` (one process/pod). Probes `/livez` (liveness) + `/readyz` (readiness). Replicas patched per overlay. |
| `notification-api` | Service | B | ClusterIP, port 80 → 8000. |
| `cpu-worker` | Deployment | B | `celery … --pool=prefork -n cpu@%h -Q cpu -c 4`. Exec liveness `inspect ping`. |
| `io-worker` | Deployment | B | `celery … --pool=threads -n io@%h -Q io -c 20`. Exec liveness `inspect ping`. |
| `frontend` | Deployment | B | nginx serving the built SPA (`__FRONTEND_IMAGE__`), port 80. |
| `frontend` | Service | B | ClusterIP, port 80. |
| `migrate-<tag>` | Job | B | One-shot `alembic upgrade head`. `backoffLimit`, `ttlSecondsAfterFinished`. Base manifest uses a **DNS-valid** placeholder token the script replaces with the sanitized per-run tag (lowercase alnum + `-`) → immutable per deploy. |
| `notification` | Ingress | B | Host rules patched per overlay: app host → `frontend`, api host → `notification-api`. |
| `notification-secrets` | Secret | **dev** | `secretGenerator` from a **gitignored** `secret.env` (created by `up-dev` from a committed `secret.env.example` template). No creds committed. |
| `postgres` | Deployment + Service | **dev** | `postgres:16.14-alpine` (pinned), `emptyDir`. |
| `rabbitmq` | Deployment + Service | **dev** | `rabbitmq:4.3.2-management` (pinned). |
| `rabbitmq-deprecated-config` | ConfigMap | **dev** | `permit-deprecated.conf` mounted into RabbitMQ. |
| `notification-secrets` | Secret | **prod** | **NOT created** — must pre-exist (managed DB/RabbitMQ URLs); `up-prod` preflights it. |

**Image references** (substituted by the script, never `latest`):

| Placeholder | dev value | prod value |
|---|---|---|
| `__API_IMAGE__` | `notification-service:dev-<sha>[-dirty-<epoch>]` (kind-loaded) | `${IMAGE_REGISTRY}/notification-service:<sha>` (pushed) |
| `__FRONTEND_IMAGE__` | `notification-frontend:dev-<sha>[…]` (kind-loaded) | `${IMAGE_REGISTRY}/notification-frontend:<sha>` (pushed) |
| Job-name tag (DNS-valid placeholder) | `dev-<sha>[…]` | `<sha>` |

> **Naming note**: the API Deployment/Service are named `notification-api`, while the container
> **image** they run is `notification-service` (built from `backend/`). The distinct names are
> intentional — a Kubernetes resource name vs a Docker image name — not a typo.

## B. Per-environment configuration matrix

| Dimension | dev | prod |
|---|---|---|
| Cluster | local **kind** (auto-created if absent) | existing **prod context** (never created) |
| Image delivery | `docker build` → `kind load docker-image` | `docker build` → `docker push ${IMAGE_REGISTRY}` |
| Datastores | in-cluster Postgres + RabbitMQ (ephemeral) | **managed/external** (via Secret) |
| Secret source | kustomize `secretGenerator` from gitignored `secret.env` (+ committed `secret.env.example`) | pre-existing `notification-secrets` (preflighted) |
| Replicas | 1 (api/workers/frontend) | overlay-configured (N) |
| Ingress hosts | `app.localhost` / `api.localhost` | configured prod hostnames |
| Ingress controller | installed into kind by `up-dev` | cluster's existing controller / LB |
| `VITE_API_BASE_URL` (frontend build) | `http://api.localhost` | configured prod API host |

## C. Configuration inputs (environment / secret keys)

Consumed by the scripts and/or workloads — never hard-coded (Principle VI; FR-009, FR-016).

| Name | Used by | Required where | Purpose / fail-fast |
|---|---|---|---|
| `IMAGE_REGISTRY` | `up-prod` | prod | Registry to push to + reference in manifests. Missing → fail fast. |
| `KUBE_CONTEXT` (or current-context) | both | both | Target cluster. Wrong/unreachable → fail fast, no apply. |
| `notification-secrets` → `database-url-async` | API | both | asyncpg URL (managed in prod, local in dev). |
| `notification-secrets` → `database-url-sync` | API, workers, migrate Job | both | psycopg v3 URL. |
| `notification-secrets` → `broker-url` | API, workers | both | RabbitMQ URL. |

## D. Bring-up lifecycle (state transitions)

Each script is a fail-fast pipeline; any stage's non-zero exit aborts the rest and propagates a
non-zero code (FR-008). Re-running converges (FR-011).

```text
up-dev.sh
  resolve repo root ──► check prereqs (docker, kind, kubectl, wsl@wrapper)
       │ missing? ──► ERROR + exit≠0 (<10s, SC-005)
       ▼
  ensure kind cluster (create w/ :80/:443 port-maps if absent; reuse if present)
       ▼
  ensure ingress-nginx installed ──► wait controller Ready
       ▼
  derive IMAGE_TAG ──► docker build api + frontend ──► (build fails ──► exit≠0, no apply)
       ▼
  kind load docker-image api + frontend
       ▼
  ensure overlays/dev/secret.env (copy from secret.env.example if absent — gitignored, no creds in git)
       ▼
  render dev overlay ─(substitute image/tag)─► kubectl apply -f -
       ▼
  kubectl wait job/migrate-<tag> --for=condition=complete   (fails ──► exit≠0)
       ▼
  kubectl rollout status deploy/{api,cpu-worker,io-worker,frontend,postgres,rabbitmq}
       ▼
  READY  (app at http://app.localhost) ──► exit 0

up-prod.sh
  resolve repo root ──► check prereqs + IMAGE_REGISTRY
       ▼
  preflight: context reachable? + notification-secrets present?
       │ no ──► ERROR + exit≠0 (no partial apply)
       ▼
  require clean tree ──► derive IMAGE_TAG=<sha> ──► docker build ──► docker push
       ▼
  render prod overlay ─(substitute)─► kubectl apply -f -
       ▼
  wait migrate Job + rollout status (api/workers/frontend)
       ▼
  report rollout success/failure via exit code (SC-003)
```

**Migration sub-lifecycle** (per deploy, FR-014 / SC-007): `Job migrate-<tag>` created → runs
`alembic upgrade head` **once** → `Complete`. API pods' `await-migrations` init container blocks on
`alembic current == head` (DB-only) before `uvicorn` starts → no replica races, no half-migrated
serving state.

## E. Validation rules (from FRs)

- Scripts MUST resolve the repo root from any CWD (FR-007, SC-008).
- Wrappers MUST be thin: only the `wsl.exe` invocation + arg/exit-code passthrough (FR-005/006, SC-004).
- `*.sh` MUST be LF via `.gitattributes` (FR-010).
- Image references MUST be the immutable per-run tag — never `latest` (FR-018).
- prod MUST fail fast if datastore connection config / secret is absent (FR-016, edge case).
- Migrations MUST run once per deploy (Job), never per replica (FR-014, SC-007).
- The runtime image MUST contain no build toolchain (FR-013, SC-006).
