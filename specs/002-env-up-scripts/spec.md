# Feature Specification: Environment Bring-Up Scripts (up-dev / up-prod)

**Feature Branch**: `002-env-up-scripts`

**Created**: 2026-06-21

**Status**: Draft

**Input**: User description: "we need 2 sh scripts, up-dev and up-prod that switch on each environment, also 2 more ps1 scripts up-dev and up-prod that call their respective up-xxx.sh through wsl.exe"

## Clarifications

### Session 2026-06-21

- Q: `up-dev` should use Kubernetes like prod — what happens to the `docker compose` dev stack? → A: **Kubernetes-only dev.** Both `up-dev` and `up-prod` deploy to Kubernetes (dev → a **local** cluster; prod → the production cluster). `docker compose` is **retired** as the dev orchestrator; this feature supersedes feature 001's compose-based dev bring-up. (Constitution amended to v1.5.0.)
- Q: Multi-stage image — which runtime base? → A: **Slim, keep the pin.** A multi-stage build (build stage compiles dependencies; runtime stage = `python:3.13.14-slim`, pinned by patch + digest) — *not* distroless, so the Python 3.13.14 pin and a shell are preserved. Schema migrations move out of the API start command into a **Kubernetes init container** (best practice for replicas; required by constitution v1.5.0).
- Q: What does each environment deploy (workloads + datastores)? → A: **Dev = full stack in-cluster** — API + cpu-worker + io-worker + Postgres + RabbitMQ as in-cluster workloads. **Prod = app only** — API + cpu/io workers, configured to use **managed/external** Postgres + RabbitMQ (not in-cluster). So the manifests expand beyond 001's API-only set to add worker Deployments and (dev only) Postgres + RabbitMQ workloads.
- Q: How are manifests structured/parametrized per environment? → A: **Kustomize.** A shared `deploy/k8s/base` (API + cpu/io workers + migration init container) with `overlays/dev` (adds in-cluster Postgres + RabbitMQ + dev config) and `overlays/prod` (managed-datastore config, replica counts, image tag). The scripts apply with `kubectl apply -k deploy/k8s/overlays/<env>` — no extra tooling beyond `kubectl`.
- Q: Dev local cluster + how does the image reach it? → A: **kind.** `up-dev` runs `docker build` then `kind load docker-image` into the local kind cluster (so the same script is CI-runnable). `up-prod` builds and **pushes to a configured container registry**, then applies. Manifests reference the immutable per-run image tag.
- Q: Is the frontend part of the Kubernetes deploy? → A: **Yes, in-cluster in both environments.** The frontend ships as its own **multi-stage** image (Node build → static assets served by a lightweight web server, e.g. nginx) with a Deployment/Service; `up-dev`/`up-prod` deploy it alongside the API. Local `npm run dev` remains available for fast HMR against the in-cluster API.
- Q: How does a developer reach the app in the cluster? → A: **Ingress in both environments.** The manifests define Ingress resources (host routes for the frontend + API). `up-dev` installs the ingress controller (ingress-nginx) into the kind cluster and creates the cluster with host port-mappings, so the app is reachable at `http://localhost` — all in-cluster containers managed by the script, **nothing installed on the developer's machine**. Prod uses the production cluster's existing ingress controller / load balancer. (Supersedes an earlier port-forward answer, which was based on a misread of "install".)
- Q: Should `up-dev` create the kind cluster if missing? → A: **Yes, auto-create (idempotent).** `up-dev` creates the local kind cluster if absent and reuses it if present, so the only cluster prerequisite for dev is that `kind` is installed. `up-prod` never creates/destroys clusters — it targets the existing production cluster context.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One-command dev bring-up on Kubernetes (Priority: P1)

As a developer, I can stand up the entire **dev** environment on my **local Kubernetes cluster** with a
single command and have every workload come up healthy — without remembering the underlying `kubectl`
/ build steps.

**Why this priority**: This is the everyday entrypoint and the one that gives dev/prod parity (same
orchestrator as prod). It delivers the most value first.

**Independent Test**: From a clean checkout against a running local cluster, run the dev bring-up
entrypoint (the `.ps1` on Windows or the `.sh` directly on Linux) and confirm all workloads reach a
healthy/ready state with no manual steps.

**Acceptance Scenarios**:

1. **Given** a running local cluster and a clean checkout on Windows, **When** the developer runs
   `up-dev.ps1`, **Then** the app image is built and the dev manifests are applied, and every workload
   reaches Ready with no additional manual commands.
2. **Given** the same on Linux/CI, **When** the developer runs `scripts/up-dev.sh`, **Then** the bring-up
   behaves identically.
3. **Given** the dev environment is already deployed, **When** the script is run again, **Then** it
   completes safely (idempotent — declarative apply) without corrupting the running environment.

---

### User Story 2 - One-command prod bring-up on Kubernetes (Priority: P2)

As an operator/developer, I can deploy the **prod** environment to the **production cluster** with a
single command.

**Why this priority**: A matching prod entrypoint gives a single, documented way to deploy the
production topology; used less often than dev, hence P2.

**Independent Test**: Run the prod bring-up entrypoint against the production context and confirm it
applies the production topology and reports rollout success/failure via its exit code.

**Acceptance Scenarios**:

1. **Given** a configured production cluster context, **When** the operator runs `up-prod.ps1` (or
   `scripts/up-prod.sh`), **Then** the production manifests are applied with prod configuration and the
   command reports rollout success.
2. **Given** the production context is unreachable/misconfigured, **When** the script runs, **Then** it
   fails fast with a clear message and a non-zero exit code (no silent partial apply).

---

### User Story 3 - Windows → WSL parity (thin wrappers, one source of truth) (Priority: P3)

As a developer on Windows, I can run the same logic my Linux/CI/container teammates run, because the
PowerShell entrypoints are **thin wrappers** that invoke the canonical bash scripts through `wsl.exe`.

**Why this priority**: Single-sourcing logic in bash guarantees the behavior tested on Windows is the
behavior that runs in CI, containers, and prod (all Linux). A correctness/maintainability property on
top of US1/US2.

**Independent Test**: Inspect the wrappers (only the WSL invocation, no orchestration logic), then
confirm arguments pass through and the bash script's exit code is propagated back to PowerShell.

**Acceptance Scenarios**:

1. **Given** `up-dev.ps1`/`up-prod.ps1`, **When** reviewed, **Then** they contain no orchestration
   logic — only the `wsl.exe` call to the matching `.sh` — so logic exists in exactly one place.
2. **Given** a wrapper invoked with extra arguments, **When** it runs, **Then** those arguments are
   forwarded unchanged to the bash script.
3. **Given** the bash script exits non-zero, **When** the wrapper finishes, **Then** PowerShell returns
   that same non-zero exit code (failures are not masked).

---

### Edge Cases

- **WSL not installed/configured** on Windows → the `.ps1` wrapper fails fast with an actionable
  message, non-zero exit.
- **No reachable cluster / wrong kube-context** → the script fails fast with a clear message and
  non-zero exit (it must not apply to the wrong cluster).
- **Prod managed-datastore config missing** → `up-prod` fails fast — there is no in-cluster
  Postgres/RabbitMQ fallback in prod; it must not deploy an app that cannot reach its data layer.
- **Image build fails / build prerequisites missing** → the script stops before applying manifests.
- **Migration init container fails** → the API workload does not start; the script surfaces the failure
  and exits non-zero (no half-migrated, serving state).
- **Script invoked from a subdirectory** → it still operates against the repository root.
- **Windows line endings (CRLF)** on the `.sh` files → would break execution under WSL/bash; the bash
  scripts MUST remain LF so a Windows checkout still runs them correctly.
- **Re-run while already deployed** → safe/idempotent (declarative apply); no duplicate/corrupted state.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The project MUST provide an executable `up-dev` bash script that, in a single command,
  builds the app image and deploys the full application to a **local Kubernetes cluster** (dev config).
- **FR-002**: The project MUST provide an executable `up-prod` bash script that, in a single command,
  deploys the application to the **production Kubernetes cluster** (prod config).
- **FR-003**: Each script MUST target its environment's cluster context and apply environment-specific
  configuration (context/namespace, image tag, replica count, secrets source) via the project's
  Kubernetes manifests/overlays.
- **FR-004**: The project MUST provide `up-dev.ps1` and `up-prod.ps1` Windows entrypoints that invoke
  their corresponding bash script via `wsl.exe`.
- **FR-005**: The PowerShell entrypoints MUST be **thin wrappers** containing no orchestration logic;
  all logic lives in the bash scripts (single source of truth → dev/CI/container/prod parity).
- **FR-006**: The wrappers MUST forward any passed arguments to the bash script and MUST propagate the
  bash script's exit code back to the caller.
- **FR-007**: Every script MUST operate against the repository root regardless of the caller's CWD.
- **FR-008**: Every script MUST exit `0` on success and non-zero on failure (usable in automation/CI).
- **FR-009**: Every script MUST fail fast with a clear, actionable message when a prerequisite is
  missing (WSL for the wrappers; `kind` / `kubectl` / Docker installed; a reachable **prod** cluster
  context for `up-prod`).
- **FR-010**: The bash scripts MUST use LF line endings (enforced via `.gitattributes`) so they execute
  correctly under WSL/Linux even on a Windows checkout.
- **FR-011**: Re-running a script MUST be safe (idempotent) — a declarative apply MUST NOT corrupt or
  duplicate state.
- **FR-012**: The scripts MUST surface readiness — wait for / report rollout success, or report which
  workload failed.
- **FR-013**: The application container image MUST be built **multi-stage** — a build stage (toolchain +
  dependency compilation) separate from a minimal runtime stage based on `python:3.13.14-slim` (pinned
  patch version + digest), carrying no build tools.
- **FR-014**: Schema migrations MUST run as a **Kubernetes init container** (or one-shot Job) before the
  API serves traffic — NOT from the API container's start command — so replicas never race to migrate.
- **FR-015**: This feature MUST retire `docker compose` as the dev orchestrator (superseding feature
  001's compose-based bring-up) and update the operating manual / dev docs accordingly.
- **FR-016**: The Kubernetes manifests MUST cover all app workloads — API, **cpu** worker, **io**
  worker (separate Deployments with pool-identifying nodenames), and the **frontend** (its own
  multi-stage image: Node build → static assets served by a lightweight web server such as nginx;
  Deployment + Service). The **dev** configuration MUST additionally deploy **in-cluster Postgres +
  RabbitMQ**; the **prod** configuration MUST omit those and wire the app to **managed/external**
  Postgres + RabbitMQ via secrets/config, failing fast if that connection configuration is absent.
- **FR-017**: The manifests MUST be organized with **Kustomize** — a shared `deploy/k8s/base` plus
  `overlays/dev` and `overlays/prod`; `up-dev`/`up-prod` MUST deploy via
  `kubectl apply -k deploy/k8s/overlays/<env>` (no tooling beyond `kubectl`).
- **FR-018**: `up-dev` MUST build the image and load it into a local **kind** cluster
  (`kind load docker-image`); `up-prod` MUST build and push the image to a configured container
  registry before applying. Manifests MUST reference the immutable per-run tag (no `latest`).
- **FR-019**: The app MUST be reachable via **Ingress** in both environments — the manifests define
  Ingress resources routing to the frontend and API. `up-dev` MUST ensure an ingress controller
  (ingress-nginx) is installed in the kind cluster so the app is reachable at `http://localhost`
  (in-cluster containers managed by the script; nothing installed on the developer's machine). **Prod**
  relies on the production cluster's ingress controller / load balancer.
- **FR-020**: `up-dev` MUST ensure the local **kind** cluster exists — creating it if absent (with the
  host port-mappings the ingress controller needs), reusing it if present (idempotent) — so the only
  cluster prerequisite for dev is that `kind` is installed.
  `up-prod` MUST NOT create or destroy clusters; it targets the existing production cluster context.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From a clean checkout on Windows (with a running local cluster), a developer brings the
  full dev environment to Ready with a single command and zero manual follow-up steps.
- **SC-002**: The same dev bash script runs unchanged on Linux/CI and yields the same result (parity).
- **SC-003**: `up-prod` applies the production topology and reports rollout success/failure via its exit
  code in 100% of runs.
- **SC-004**: 100% of orchestration logic resides in the bash scripts; each PowerShell wrapper contains
  only the WSL invocation (a handful of lines, no environment logic).
- **SC-005**: A missing prerequisite (no WSL / no cluster / failed build) produces a clear error and a
  non-zero exit within 10 seconds (no hanging).
- **SC-006**: The runtime image contains **no build toolchain** (e.g., `uv` is absent) and is materially
  smaller than an equivalent single-stage image.
- **SC-007**: Migrations execute exactly **once per deploy** (init container/Job), never once-per-replica.
- **SC-008**: Running any script from a subdirectory behaves identically to running it from the repo root.

## Assumptions

- **"dev environment"** = the application deployed to a **local kind cluster**. **"prod environment"** =
  the application deployed to the **production
  cluster**. Both use the project's Kubernetes manifests with per-environment configuration/overlays.
- **Datastores**: dev runs Postgres + RabbitMQ **in-cluster** (ephemeral local data is acceptable); prod
  uses **managed/external** Postgres + RabbitMQ supplied via secrets/config (provisioning those managed
  services is out of scope).
- **Image delivery**: dev builds + `kind load`s the image into the local cluster; prod builds + pushes to
  a configured container registry (registry + credentials supplied via config — provisioning the
  registry is out of scope).
- A working `kubectl` (plus `kind` + Docker for dev) is required. `up-dev` **creates the local kind
  cluster if missing**; `up-prod` targets an **existing** production cluster context (it does not
  provision prod). Windows developers have **WSL + a Linux distro** (with `kubectl` / `kind` / Docker on
  PATH) available; the wrappers target `wsl.exe`.
- Script layout matches the requested shape — bash scripts under `scripts/` and PowerShell wrappers at
  the repository root (`up-dev.ps1` → `wsl.exe bash ./scripts/up-dev.sh`). Per-environment manifests use
  **Kustomize** (`deploy/k8s/base` + `overlays/{dev,prod}`, applied via `kubectl apply -k`).
- This feature reworks existing artifacts to match constitution v1.5.0: `backend/Dockerfile` becomes
  multi-stage (slim runtime), `deploy/k8s/` gains a dev overlay + a migration init container, and
  `docker-compose.yml` + the compose-based dev docs (CLAUDE.md, 001 quickstart) are retired/updated.
- Aligns with the constitution's Operations principle (dev + prod on Kubernetes; multi-stage images;
  migrations as an init container). The "bash-canonical + thin PowerShell wrapper" convention is the
  new project standard introduced here.

## Out of Scope

- Provisioning the Kubernetes clusters, WSL, or `kubectl` themselves.
- The CI/CD pipeline internals (CD already deploys prod via GitHub Actions; it MAY later reuse these
  manifests, but pipeline changes are not part of this feature).
- Environments other than `dev` and `prod`.
- Tear-down / `down` scripts (only bring-up is requested).
- Application features, migration contents, or the analytics seed script.
