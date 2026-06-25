---
description: "Task list for feature 002-env-up-scripts implementation"
---

# Tasks: Environment Bring-Up Scripts (up-dev / up-prod)

**Input**: Design documents from `specs/002-env-up-scripts/`
**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: This is a pure ops/infra feature — it adds **no application code** (no API, persistence, or
channel changes), so the constitution's pytest/Testcontainers mandate (Principle V) does not apply and
no `pytest` tasks are generated. Validation is via `shellcheck`, `kubectl --dry-run` / `kubeconform`,
and the [quickstart.md](./quickstart.md) scenarios (Phase 6). The existing app test suite is untouched.

**Organization**: Tasks are grouped by user story. The multi-stage images + Kustomize `base` are
shared by US1 and US2, so they live in **Foundational** (Phase 2); each story phase adds only its
environment-specific delta.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 / US2 / US3 (Setup/Foundational/Polish carry no story label)

## Path Conventions

Monorepo: `backend/`, `frontend/`, repo-root ops tooling (`scripts/`, `deploy/k8s/`, `up-*.ps1`).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Repo scaffolding and the line-ending guarantee every `.sh` depends on.

- [X] T001 Create directory scaffolding: `deploy/k8s/base/`, `deploy/k8s/overlays/dev/`, `deploy/k8s/overlays/prod/`, and `scripts/lib/` (add `.gitkeep` placeholders where a dir would otherwise be empty)
- [X] T002 [P] Add repo-root `.gitattributes`: `* text=auto`, `*.sh text eol=lf`, `*.ps1 text eol=crlf` — guarantees LF `.sh` even on a Windows checkout so WSL/bash runs them (FR-010, quickstart Scenario 8)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The multi-stage images, the shared bash library, and the Kustomize `base` — all required
by BOTH `up-dev` (US1) and `up-prod` (US2).

**⚠️ CRITICAL**: No user-story phase can complete until this phase is done.

- [X] T003 [P] Rework `backend/Dockerfile` into an explicit multi-stage build — a build stage using the pinned `uv` (`ghcr.io/astral-sh/uv:0.11.19@sha256:…`) to `uv sync --no-dev --frozen`, and a runtime stage on `python:3.13.14-slim@sha256:…` that copies only the resolved env + app source and carries **no `uv`/build tools**; change the runtime `CMD` to `uvicorn app.main:app --host 0.0.0.0 --port 8000` (drop `alembic upgrade head`) (FR-013, FR-014, SC-006; research R6)
- [X] T004 [P] Rework `frontend/Dockerfile` into multi-stage — stage 1 `node:18.20.8-alpine@sha256:…` runs `npm ci && npm run build` (build-arg `VITE_API_BASE_URL`); stage 2 a pinned `nginx` serves `/usr/share/nginx/html` on :80 — and add `frontend/nginx.conf` with SPA history-fallback (FR-016; research R7)
- [X] T005 [P] Create `scripts/lib/common.sh` (shared, sourced by both scripts): repo-root resolution (`git rev-parse --show-toplevel` with a `dirname`-based fallback), structured `log`/`die` helpers, `require_cmd` fail-fast prereq checks, image-tag derivation (`git rev-parse --short HEAD`; dev → `dev-<sha>` + `-dirty-<epoch>` when the tree is dirty, prod → bare `<sha>` with a clean-tree guard), a `render_apply <env>` helper (`kubectl kustomize deploy/k8s/overlays/<env>` → `sed` substitute `__API_IMAGE__`/`__FRONTEND_IMAGE__`/the Job-name tag → `kubectl apply -f -`, forwarding any extra positional args to the apply per contracts/scripts-cli), and a `wait_rollout` helper (honoring `ROLLOUT_TIMEOUT`, default `180s`) (FR-007, FR-008, FR-009, FR-018; research R3, R5)
- [X] T006 Create `deploy/k8s/base/namespace.yaml` — `Namespace/notification`
- [X] T007 Create `deploy/k8s/base/api.yaml` — `Deployment/notification-api` (image `__API_IMAGE__`, single `uvicorn` container, `livenessProbe` `/livez`, `readinessProbe` `/readyz`, env from `notification-secrets`, and an `await-migrations` **init container** that polls the DB until `alembic current` is at head — no DDL) **and** `Service/notification-api` (ClusterIP 80→8000) (FR-014; contracts/kustomize-overlays K4; research R1)
- [X] T008 [P] Create `deploy/k8s/base/cpu-worker.yaml` — `Deployment/cpu-worker` (image `__API_IMAGE__`, `celery -A app.tasks.celery_app worker --pool=prefork -n cpu@%h -Q cpu -c 4`, exec liveness `celery … inspect ping -d cpu@$(hostname)`) (constitution III; research flag 5)
- [X] T009 [P] Create `deploy/k8s/base/io-worker.yaml` — `Deployment/io-worker` (image `__API_IMAGE__`, `celery … worker --pool=threads -n io@%h -Q io -c 20`, exec liveness `inspect ping -d io@$(hostname)`)
- [X] T010 [P] Create `deploy/k8s/base/frontend.yaml` — `Deployment/frontend` (image `__FRONTEND_IMAGE__`, :80) **and** `Service/frontend` (FR-016)
- [X] T011 [P] Create `deploy/k8s/base/migrate-job.yaml` — one-shot `Job` named with a **DNS-valid** per-run tag sentinel (substituted by `render_apply`; tag sanitized to lowercase-alnum+`-`), image `__API_IMAGE__`, command `alembic upgrade head`, `backoffLimit`, `ttlSecondsAfterFinished`, env from `notification-secrets` (FR-014, SC-007; research R1)
- [X] T012 [P] Create `deploy/k8s/base/ingress.yaml` — `Ingress` (ingressClassName `nginx`; two host rules — app host → `frontend:80`, api host → `notification-api:80`; placeholder hosts overlays patch; no path rewrite) (FR-019; research R2)
- [X] T013 Create `deploy/k8s/base/kustomization.yaml` referencing all base resources (T006–T012) (depends on T006–T012)

**Checkpoint**: Images build with no build tools in the runtime; `kubectl kustomize deploy/k8s/base` renders. User stories can begin.

---

## Phase 3: User Story 1 - One-command dev bring-up on Kubernetes (Priority: P1) 🎯 MVP

**Goal**: `up-dev` builds the images and brings the **full dev stack** (API + cpu/io workers +
frontend + in-cluster Postgres + RabbitMQ) up on a local **kind** cluster to Ready, with ingress at
`http://app.localhost`, in one command.

**Independent Test**: From a clean checkout, run `scripts/up-dev.sh` (or `up-dev.ps1` on Windows once
US3 lands); every workload reaches Ready with no manual steps, and `curl http://api.localhost/health`
succeeds (quickstart Scenarios 1–3, 6–8).

- [X] T014 [P] [US1] Create `deploy/k8s/kind-config.yaml` — kind cluster config: one control-plane node labeled `ingress-ready=true` with `extraPortMappings` 80→80 and 443→443 (so ingress-nginx serves on the host's :80/:443, routing `app.localhost` / `api.localhost`) (FR-019, FR-020; research R4)
- [X] T015 [P] [US1] Create `deploy/k8s/overlays/dev/postgres.yaml` — in-cluster `Deployment/postgres` + `Service/postgres` (`postgres:16.14-alpine@sha256:…`, `emptyDir`, POSTGRES_USER/PASSWORD/DB = app) (FR-016; research R8)
- [X] T016 [P] [US1] Create `deploy/k8s/overlays/dev/rabbitmq.yaml` (`Deployment/rabbitmq` + `Service/rabbitmq`, `rabbitmq:4.3.2-management@sha256:…`, mounting the config) and `deploy/k8s/overlays/dev/rabbitmq-config.yaml` (`ConfigMap` carrying `permit-deprecated.conf`, moved from `deploy/rabbitmq/`) (FR-016; research R8)
- [X] T017 [US1] Create `deploy/k8s/overlays/dev/kustomization.yaml` — `resources: [../../base, postgres.yaml, rabbitmq.yaml, rabbitmq-config.yaml]`; `secretGenerator` `notification-secrets` with `envs: [secret.env]`; image refs inherit the base `__API_IMAGE__`/`__FRONTEND_IMAGE__` placeholders — `render_apply` substitutes them with the kind-loaded `notification-{service,frontend}:dev-<sha>` (no registry); **no** kustomize `images:` transformer (research R3); replicas patch = 1; patch base ingress hosts → `app.localhost` / `api.localhost`. **Also** add a committed `deploy/k8s/overlays/dev/secret.env.example` (placeholder non-prod defaults: in-cluster Service-DNS URLs, app/app, guest/guest) and add `deploy/k8s/overlays/dev/secret.env` to `.gitignore` so no credential **values** are committed (FR-016, FR-017; Principle VI; finding C1; contracts/kustomize-overlays K6) (depends on T013, T015, T016)
- [X] T018 [US1] Implement `scripts/up-dev.sh` — source `lib/common.sh`; prereq-check `docker`/`kind`/`kubectl`; ensure the kind cluster `${KIND_CLUSTER_NAME:-notification}` from `kind-config.yaml` (create if absent, reuse if present — idempotent); install ingress-nginx from its kind-provider manifest **pinned to an explicit released `controller-vX.Y.Z` tag** (newest stable; never `main`/`latest` — Principle I; the pinned manifest digest-pins the controller image) and `kubectl wait` its controller Ready; build `notification-service:<tag>` + `notification-frontend:<tag>` (`--build-arg VITE_API_BASE_URL=http://api.localhost`); `kind load docker-image` both; ensure `overlays/dev/secret.env` exists (copy from `secret.env.example` if absent — gitignored, no creds in git); `render_apply dev`; `kubectl wait --for=condition=complete job/migrate-<tag>`; `wait_rollout` for api/cpu-worker/io-worker/frontend/postgres/rabbitmq; print the `http://app.localhost` URL (FR-001, FR-003, FR-011, FR-012, FR-018, FR-019, FR-020; contracts/scripts-cli C2/C4/C5) (depends on T005, T013, T014, T017)

**Checkpoint**: `scripts/up-dev.sh` brings dev to Ready and is idempotent on re-run — the MVP.

---

## Phase 4: User Story 2 - One-command prod bring-up on Kubernetes (Priority: P2)

**Goal**: `up-prod` builds + pushes images and deploys the **app-only** prod topology (managed
external datastores) to the existing production cluster, reporting rollout success via exit code.

**Independent Test**: Against a configured prod context with `IMAGE_REGISTRY` and a pre-existing
`notification-secrets`, run `scripts/up-prod.sh` → it applies and reports rollout success (exit 0);
with the secret/context missing it fails fast (exit ≠0, no partial apply) (quickstart Scenario 4).

- [X] T019 [US2] Create `deploy/k8s/overlays/prod/kustomization.yaml` (+ `deploy/k8s/overlays/prod/replicas-patch.yaml` and an ingress-hosts patch) — `resources: [../../base]` **only**; image refs inherit the base `__API_IMAGE__`/`__FRONTEND_IMAGE__` placeholders — `render_apply` substitutes them with `${IMAGE_REGISTRY}/notification-{service,frontend}:<sha>` (post-render `sed`; kustomize can't expand `${IMAGE_REGISTRY}` or inject a per-run tag from a committed file — research R3, FR-017); replicas patch = N; ingress hosts → configured prod hostnames; **NO** in-cluster datastores and **NO** committed Secret (FR-016, FR-017; contracts/kustomize-overlays K5) (depends on T013)
- [X] T020 [US2] Implement `scripts/up-prod.sh` — source `lib/common.sh`; require `IMAGE_REGISTRY`; **preflight** the target context (`kubectl cluster-info`) and that `notification-secrets` exists in the namespace, failing fast with an actionable message and no apply if either is missing; require a clean tree; derive `<sha>`; `docker build` + `docker push` api+frontend to `${IMAGE_REGISTRY}`; `render_apply prod`; `kubectl wait` the migrate Job + `wait_rollout` api/cpu-worker/io-worker/frontend; exit code reflects rollout success/failure; never create/destroy clusters (FR-002, FR-003, FR-009, FR-012, FR-016, FR-018, FR-020; contracts/scripts-cli C3) (depends on T005, T013, T019)

**Checkpoint**: Both `up-dev` and `up-prod` work independently against their respective clusters.

---

## Phase 5: User Story 3 - Windows → WSL parity (thin wrappers) (Priority: P3)

**Goal**: PowerShell entrypoints let Windows developers run the exact bash logic teammates/CI run,
forwarding args and propagating the bash exit code — with no orchestration logic of their own.

**Independent Test**: Inspect each `.ps1` (only the `wsl.exe` call + exit-code passthrough); invoke a
wrapper with extra args and force a bash failure → args are forwarded and the same non-zero code comes
back (quickstart Scenario 5).

- [X] T021 [P] [US3] Create repo-root `up-dev.ps1` — a thin wrapper: a minimal `wsl.exe`-presence guard (actionable message + non-zero exit if absent), then `wsl.exe bash "./scripts/up-dev.sh" @args` and `exit $LASTEXITCODE`; no environment/orchestration logic (FR-004, FR-005, FR-006, FR-009, SC-004; contracts/scripts-cli C6)
- [X] T022 [P] [US3] Create repo-root `up-prod.ps1` — identical thin wrapper around `./scripts/up-prod.sh` (FR-004, FR-005, FR-006, SC-004)

**Checkpoint**: All three stories independently functional; Windows parity verified.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Retire the superseded compose flow, fold legacy manifests, refresh docs, and validate.

- [X] T023 [P] Remove `docker-compose.yml` — the dev orchestrator is retired by this feature (FR-015)
- [X] T024 [P] Remove the now-folded `deploy/k8s/deployment.yaml` and `deploy/k8s/service.yaml` (absorbed into `base/api.yaml`) and `deploy/rabbitmq/permit-deprecated.conf` (moved to the dev ConfigMap); confirm nothing else references them
- [X] T025 [P] Update `CLAUDE.md` — Environments + Commands tables: replace the `docker compose up` dev bring-up with `scripts/up-dev.sh` / `up-dev.ps1` on kind; note the `up-prod` counterparts (FR-015)
- [X] T026 [P] Update `README.md` dev bring-up instructions (docker compose → up-dev on kind) (FR-015)
- [X] T027 [P] Update `specs/001-system-liveness/quickstart.md` — replace its `docker compose up` references with the new k8s bring-up (FR-015)
- [X] T028 Adjust **only** the manifest-validation step in `.github/workflows/cd.yml` to validate rendered overlays (`kubectl kustomize deploy/k8s/overlays/{dev,prod}` piped to `kubeconform`) instead of the removed flat `deploy/k8s/` files, keeping CI green after the restructure — now permitted by the spec's Out-of-Scope carve-out (validation only; CD/deployment redesign remains out of scope). While editing this step, also **pin the `kubeconform` download to an explicit released tag** (replace the `releases/latest/download/…` URL — Principle I, no floating tags). Leave the CD **deploy** job's `kubectl apply -f deploy/k8s/` / `set image` lines **unchanged** — they are echo-stubbed and the CD redesign stays out of scope, even though they still reference the pre-restructure layout
- [X] T029 [P] Run `shellcheck scripts/lib/common.sh scripts/up-dev.sh scripts/up-prod.sh` and resolve findings
- [X] T030 Run the [quickstart.md](./quickstart.md) validation scenarios 1–8 (dev bring-up, idempotent re-run, run-from-subdirectory, prod fail-fast, wrapper exit-code propagation, runtime image has no `uv`, migrations once-per-deploy, LF guard). **Validated live** on a `kind` v0.32.0 cluster (k8s v1.36.1, Docker 28.5.1, WSL): **S1** dev bring-up exits 0 — all 6 Deployments (api, cpu/io workers, frontend, postgres, rabbitmq) + ingress Ready; `/livez`,`/readyz`,`/health` all 200 with data_store/message_broker/cpu/io checks green; `app.localhost` HTTP 200. **S2** idempotent re-run — kind cluster reused, converges, exit 0. **S3** run from `backend/` subdir — identical behavior (repo-root resolution). **S4** prod fail-fast — missing `IMAGE_REGISTRY` exits 1 in 0s, unknown `KUBE_CONTEXT` exits 1 in 1s (both <10s, SC-005), no partial apply (namespace unchanged). **S5** `up-prod.ps1` propagates the bash non-zero exit via `$LASTEXITCODE`. **S6** `NO_UV` + app imports; runtime image **354 MB** (`docker images`) — note the quickstart's `docker image inspect --format '{{.Size}}'` prints ~80 MB, the containerd-snapshotter figure, not the on-disk size. **S7** one `migrate-<tag>` Job Complete; API init container `await-migrations` only waits (no alembic); the Job's `backoffLimit` rides out the Postgres-readiness race. **S8** `.sh` LF / 0 CR bytes. Static gates: `shellcheck` v0.10.0 clean on all three scripts; `kubeconform` v0.6.7 strict — base 9/9, dev 15/15, prod 9/9, 0 skipped; both Docker images build. Existing pytest suite green (15 passed) after the conftest fixture move.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies — start immediately.
- **Foundational (Phase 2)**: depends on Setup — **blocks all user stories**.
- **US1 (Phase 3)**: depends on Foundational. The MVP.
- **US2 (Phase 4)**: depends on Foundational. Independent of US1 (shares only `base`).
- **US3 (Phase 5)**: wrappers are trivial, but **meaningful testing depends on US1/US2 scripts
  existing** (the spec rates US3 a P3 property "on top of US1/US2").
- **Polish (Phase 6)**: depends on the stories it touches (T023–T027 after the manifests/scripts they
  replace exist; T030 after US1–US3).

### Within-phase dependencies

- T013 (base kustomization) depends on T006–T012.
- T017 (dev overlay) depends on T013, T015, T016. T018 (`up-dev.sh`) depends on T005, T013, T014, T017.
- T019 (prod overlay) depends on T013. T020 (`up-prod.sh`) depends on T005, T013, T019.

### Parallel Opportunities

- **Setup**: T002 ∥ T001.
- **Foundational**: T003, T004, T005 (images + lib) ∥ each other; the base resource files T006–T012
  are independent files — T008–T012 ∥ (T007 carries the API+Service; T013 gates on all).
- **US1**: T014, T015, T016 ∥ (then T017 → T018).
- **US3**: T021 ∥ T022.
- **Polish**: T023, T024, T025, T026, T027, T029 ∥ (T028 and T030 run on their own).
- With capacity, US1 and US2 overlays/scripts can be built in parallel once Foundational is done.

---

## Parallel Example: Foundational base manifests

```bash
# After T006/T007, the remaining base resources are independent files:
Task: "T008 cpu-worker Deployment in deploy/k8s/base/cpu-worker.yaml"
Task: "T009 io-worker Deployment in deploy/k8s/base/io-worker.yaml"
Task: "T010 frontend Deployment+Service in deploy/k8s/base/frontend.yaml"
Task: "T011 migrate Job in deploy/k8s/base/migrate-job.yaml"
Task: "T012 Ingress in deploy/k8s/base/ingress.yaml"
# then T013 assembles base/kustomization.yaml
```

## Parallel Example: User Story 1 dev overlay

```bash
Task: "T014 kind cluster config in deploy/k8s/kind-config.yaml"
Task: "T015 in-cluster Postgres in deploy/k8s/overlays/dev/postgres.yaml"
Task: "T016 in-cluster RabbitMQ + ConfigMap in deploy/k8s/overlays/dev/rabbitmq*.yaml"
# then T017 (dev kustomization) → T018 (up-dev.sh)
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational (CRITICAL — shared images + base) → 3. Phase 3 US1.
4. **STOP and VALIDATE**: run quickstart Scenarios 1–3 — dev to Ready, idempotent, from a subdir.
5. Demo the local kind bring-up at `http://app.localhost`.

### Incremental Delivery

1. Setup + Foundational → foundation ready.
2. US1 (`up-dev`) → validate → demo (MVP).
3. US2 (`up-prod`) → validate fail-fast + rollout → demo.
4. US3 (`.ps1` wrappers) → validate Windows parity.
5. Polish: retire compose, fold legacy manifests, refresh docs, keep CI green, run full quickstart.

---

## Notes

- [P] = different files, no incomplete dependencies.
- This feature adds no app code → no pytest tasks; validation is shellcheck + `kubectl --dry-run`/
  kubeconform + the quickstart scenarios.
- Keep all images pinned by patch + digest and the deployed image on an immutable per-run tag — never
  `latest` (FR-018, Principle I).
- `.ps1` wrappers must stay thin (FR-005) — if you find yourself adding logic, it belongs in the `.sh`.
- Commit after each task or logical group; stop at any checkpoint to validate a story independently.
