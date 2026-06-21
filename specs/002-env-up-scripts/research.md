# Phase 0 Research: Environment Bring-Up Scripts

Decisions backing [plan.md](./plan.md). Every spec **NEEDS CLARIFICATION** is resolved either by the
spec's own eight Clarifications or below. Format: **Decision / Rationale / Alternatives considered.**

---

## R1. Migration execution topology (reconcile "init container" with SC-007)

**Decision**: A **one-shot per-deploy Kubernetes Job** named `migrate-<image-tag>` runs
`alembic upgrade head` exactly once. The API Deployment carries a lightweight **`await-migrations`
init container** (same app image) that blocks until the schema is at head but performs **no DDL**.
The bring-up script also runs `kubectl wait --for=condition=complete job/migrate-<tag>
--timeout=…` so a failed migration fails the script with a non-zero exit. The Job sets
`ttlSecondsAfterFinished` so finished Jobs are garbage-collected; because the name is suffixed with
the immutable per-run tag, each deploy creates a fresh immutable Job and a same-tag re-run is a no-op
(idempotent).

**Rationale**: SC-007 requires migrations to run "exactly once per deploy, never once-per-replica."
A plain init container on a ≥2-replica Deployment runs in **every pod** → concurrent
`alembic upgrade head` can race/deadlock on the version table. A Job runs once; the wait-init still
gives the "API does not serve until migrated" guarantee the v1.5.0 clarification intended, without
giving the API pod cluster-API/RBAC access (it only talks to Postgres). FR-014 explicitly allows
"init container **or** one-shot Job"; this composes both for the strongest guarantee.

**Alternatives considered**:
- *Init container runs the migration in the API pod* — simplest manifest, but per-replica → violates
  SC-007 (the exact race the constitution warns about).
- *`alembic upgrade head` back in the API CMD* — what 001 did; forbidden by FR-014 / constitution
  v1.5.0.
- *Init container `kubectl wait`s on the Job* — needs RBAC (a ServiceAccount that can read Jobs) in
  every API pod; rejected in favour of a DB-only `alembic current == head` poll.

---

## R2. Ingress routing & frontend → API wiring

**Decision**: **Two hosts, no path rewrite** (user-selected). Dev Ingress routes `app.localhost` →
frontend Service and `api.localhost` → API Service; the API keeps its native top-level paths
(`/livez`, `/readyz`, `/health`, …). The frontend image is built with
`VITE_API_BASE_URL=http://api.localhost` for dev; the prod overlay supplies the configured prod
hostnames. `*.localhost` resolves to loopback in modern browsers (Chrome/Firefox per RFC 6761) and is
documented with an `/etc/hosts` fallback for other resolvers.

**Rationale**: Host-based split keeps the API contract clean (no `/api` prefix, no rewrite annotation,
no divergence between in-cluster paths and the paths pytest/respx already exercise). It matches "the
manifests define Ingress resources (host routes for the frontend + API)" verbatim and reaches the app
at `http://app.localhost` with kind's host port-mapping on 80.

**Alternatives considered**:
- *Single host, path-based (`/` → frontend, `/api/*` → API with a rewrite)* — one host, but needs a
  rewrite annotation and shifts the API to an `/api` prefix that the app's routers/tests don't use;
  more moving parts for no benefit here.
- *Port-forward / NodePort* — the spec's clarification supersedes the earlier port-forward answer;
  ingress is required in both environments.

---

## R3. Injecting an immutable per-run image tag with kubectl only

**Decision**: Base/overlay manifests carry two kinds of sentinel placeholder: `__API_IMAGE__` and
`__FRONTEND_IMAGE__` in `image:` **string** fields (underscores are fine in string values), plus a
**DNS-1123-valid** token (lowercase, no underscores — e.g. `imagetagslot`) used **only** in the
migrate Job's `name` so the un-substituted base still validates under `kubeconform`/`--dry-run`. The
script renders the overlay with kubectl's **built-in** kustomize
(`kubectl kustomize deploy/k8s/overlays/<env>`), substitutes the per-run values (sanitizing the tag to
a DNS label for the Job name), and pipes to `kubectl apply -f -`:

```sh
kubectl kustomize deploy/k8s/overlays/dev \
  | sed -e "s|__API_IMAGE__|${API_IMAGE}|g" \
        -e "s|__FRONTEND_IMAGE__|${FRONTEND_IMAGE}|g" \
        -e "s|migrate-imagetagslot|migrate-${IMAGE_TAG_DNS}|g" \
  | kubectl apply -f -
```

**Rationale**: `kubectl apply -k` cannot inject a per-run image override from the CLI, and FR-017
forbids "tooling beyond kubectl" — so `kustomize edit set image` (standalone binary) is out. Rendering
with the built-in kustomize then substituting keeps everything kubectl-only while letting an immutable
tag flow in (FR-018: no `latest`). The result is still a declarative `apply` (idempotent, FR-011).

**Alternatives considered**:
- *`kustomize edit set image` in the overlay* — reintroduces a standalone `kustomize` dependency
  (violates FR-017) and mutates a tracked file.
- *In-place `sed` of the overlay file + `apply -k` + git-restore* — mutates tracked files mid-run;
  fragile if interrupted.
- *Helm* — disproportionate; the spec explicitly scopes to Kustomize + kubectl.

**Tag scheme**: `IMAGE_TAG = git rev-parse --short HEAD`; dev → `dev-<sha>` (+ `-dirty-<epoch>` when
`git status --porcelain` is non-empty, since dev rebuilds against an uncommitted tree); prod → bare
`<sha>` and refuses a dirty tree. dev `API_IMAGE = notification-service:<tag>` (kind-loaded, no
registry); prod `API_IMAGE = ${IMAGE_REGISTRY}/notification-service:<tag>` (built + pushed). The tag is
already a valid DNS-1123 label (lowercase hex + `-`, bounded length), so `IMAGE_TAG_DNS` is the same
value defensively lowercased/sanitized for the Job name.

---

## R4. Local cluster lifecycle: kind auto-create + ingress reachability

**Decision**: `up-dev` is idempotent over the cluster: `kind get clusters | grep -qx <name>` →
create only if absent, with a `kind` config that maps host ports **80/443 → the control-plane node**
and labels it `ingress-ready=true`; then install **ingress-nginx** (the kind-provider manifest) and
`kubectl wait` for its controller to be Ready before applying app manifests. The image reaches the
cluster via `kind load docker-image <ref>` (no registry in dev). `up-prod` **never** creates or
destroys a cluster — it targets the existing prod context and relies on that cluster's ingress
controller / load balancer.

**Rationale**: FR-020 makes "kind installed" the only dev cluster prerequisite; FR-019 requires the
app reachable on the host (`http://app.localhost` / `http://api.localhost`) with **nothing installed
on the host**. kind's documented `extraPortMappings` + `ingress-ready` node label is the canonical way
to expose ingress-nginx on host :80 so those `*.localhost` hosts work. `kind load` keeps the same
script CI-runnable (no registry round-trip for dev).

**Alternatives considered**: minikube/Docker-Desktop (spec names kind specifically; kind is the most
CI-friendly and scriptable); a local registry container (`kind load` is simpler and needs no extra
service); MetalLB (overkill for single-node local ingress).

---

## R5. Bash-canonical scripts + thin PowerShell wrappers + LF enforcement

**Decision**: All orchestration lives in `scripts/up-dev.sh` / `scripts/up-prod.sh` (sharing
`scripts/lib/common.sh`). Each resolves the repo root from its own location
(`cd "$(git rev-parse --show-toplevel)"`, or a `dirname`-based fallback) so it runs identically from
any CWD (FR-007, SC-008). The PowerShell wrappers contain only:

```powershell
wsl.exe bash "./scripts/up-dev.sh" @args
exit $LASTEXITCODE
```

— no environment logic (FR-005, SC-004), forwarding all args (FR-006) and propagating the bash exit
code (FR-006, US3 scenario 3). `.gitattributes` pins `*.sh text eol=lf` (and `*.ps1 text eol=crlf`)
so a Windows checkout still produces LF `.sh` files that execute under WSL (FR-010). The wrappers
fail fast with an actionable message if `wsl.exe` is absent (edge case / FR-009).

**Rationale**: Single-sourcing logic in bash guarantees the behaviour tested on Windows is the
behaviour that runs in CI/containers/prod (all Linux) — the whole point of US3. CRLF on a `.sh` under
bash yields `\r`-mangled shebang/commands, so the `.gitattributes` LF pin is load-bearing.

**Alternatives considered**: duplicating logic in PowerShell (two sources of truth → drift, rejected
by FR-005); `git config core.autocrlf` (per-clone, not enforced in-repo — `.gitattributes` is the
durable fix).

---

## R6. Multi-stage application image (build stage + minimal pinned runtime)

**Decision**: Convert `backend/Dockerfile` to an explicit **build → runtime** split. The build stage
uses the pinned `uv` (already `ghcr.io/astral-sh/uv:0.11.19@sha256:…`) to `uv sync --no-dev --frozen`
into a self-contained environment; the **runtime** stage is the existing
`python:3.13.14-slim@sha256:…`, copies only the resolved environment + app source, and carries **no
`uv` and no build toolchain**. The runtime **CMD drops `alembic upgrade head`** and becomes just
`uvicorn app.main:app --host 0.0.0.0 --port 8000` (migrations now run in the Job — FR-014). Worker
and migrate workloads override the command (`celery …`, `alembic upgrade head`) but share the image.

**Rationale**: FR-013 + constitution v1.5.0 require a build/runtime split with no build tools in the
runtime and the slim pin preserved (SC-006: `uv`/compilers absent — the authoritative check — and a
consequently smaller image). Keeping a single
shared image (one build, command-overridden per workload) matches how compose/k8s already invoke it.

**Alternatives considered**: distroless runtime (the clarification explicitly chose slim to keep the
3.13.14 pin + a shell); separate per-workload images (unnecessary — command override suffices).

---

## R7. Frontend as its own multi-stage image (Node build → nginx)

**Decision**: Replace the current dev-server `frontend/Dockerfile` (`npm run dev`) with a multi-stage
build: stage 1 `node:18.20.8-alpine` (pinned by digest) runs `npm ci && npm run build`; stage 2 a
pinned `nginx` serves `/dist` as static assets with an SPA-fallback config, exposing :80. A
Deployment + Service front it, and the Ingress routes the frontend host to it. `VITE_API_BASE_URL` is
baked at build time (dev: `http://api.localhost`). Local `npm run dev` remains available for HMR
against the in-cluster API.

**Rationale**: FR-016 requires the frontend to ship as its own multi-stage image (Node build → static
assets via a lightweight server). A dev server in-cluster is wrong for a deployment artifact; nginx
serving the built bundle is the standard, small, production-shaped result.

**Alternatives considered**: Caddy/`busybox httpd` (nginx is conventional and already used in
examples); serving static assets from the API (couples frontend to the API image, rejected).

---

## R8. Dev vs prod datastores & secret strategy

**Decision**: **dev** overlay adds in-cluster **Postgres** + **RabbitMQ** Deployments + Services
(pinned `postgres:16.14-alpine` / `rabbitmq:4.3.2-management` from the retired compose, `emptyDir`
storage), the RabbitMQ `permit-deprecated.conf` carried as a ConfigMap, and a kustomize
`secretGenerator` building `notification-secrets` from a **gitignored `secret.env`** (not committed).
`up-dev` creates `secret.env` from a committed **`secret.env.example`** template (placeholder
non-production defaults — `app/app`, `guest/guest`, in-cluster Service DNS URLs) on first run if it is
absent, so dev stays one-command while **no credential values are committed to git**. **prod** overlay
omits the datastores and **references an externally-created** `notification-secrets` (managed Postgres
+ RabbitMQ URLs); `up-prod` **preflights** `kubectl get secret notification-secrets -n <ns>` and fails
fast with an actionable message if absent (edge case / FR-016 — no in-cluster fallback in prod).

**Rationale**: Constitution VI states secrets MUST NEVER be committed to source control. Even though
local dev datastore creds are ephemeral throwaways, the literal rule is honoured by the standard
`*.example` + gitignored-`.env` pattern: the consumed `secret.env` is git-ignored and the only
committed file is an example template (the same category as `settings.py`'s defaults). This keeps
Principle VI absolute (no carve-out needed) while preserving one-command dev. (Resolves analysis
finding **C1**.)

**Alternatives considered**: committing the dev literals directly via `secretGenerator` + a
Constitution VI carve-out (rejected — keeps the constitution's "never committed" rule absolute
instead); generating random per-run dev creds and wiring them into the datastore workloads too
(more moving parts than the ephemeral local cluster needs); in-cluster datastores in prod (explicitly
excluded by the spec); StatefulSets + PVCs for dev (heavier than the "ephemeral acceptable"
assumption needs).

---

## R9. Idempotent apply + readiness/rollout wait

**Decision**: Deploys are declarative `kubectl apply` (re-run = converge, never duplicate — FR-011).
After applying, the scripts surface readiness (FR-012, SC-003): `kubectl wait
--for=condition=complete job/migrate-<tag>` then `kubectl rollout status deploy/<name>` for each
Deployment, with bounded `--timeout`s; any failure exits non-zero and names the failing workload.
`up-prod` additionally preflights the context (`kubectl config current-context` /
`kubectl cluster-info`) and the prod secret before any apply, so a misconfigured context fails fast
with no partial apply (US2 scenario 2, edge cases).

**Rationale**: Declarative apply gives idempotency for free; explicit `wait`/`rollout status` turns
"applied" into "actually Ready" and gives the non-zero-on-failure contract automation needs.

**Alternatives considered**: `kubectl apply` without waiting (can't report rollout success — fails
SC-003); imperative `create`/`replace` (not idempotent).

---

## R10. Retiring docker compose & updating docs

**Decision**: Remove `docker-compose.yml`; fold `deploy/k8s/deployment.yaml` + `service.yaml` into
`base/api.yaml`; move `deploy/rabbitmq/permit-deprecated.conf` into the dev ConfigMap. Update
`CLAUDE.md` (Environments/Commands tables), `README.md`, and `specs/001-system-liveness/quickstart.md`
so the documented dev bring-up is `up-dev` on kind, not `docker compose up` (FR-015).

**Rationale**: FR-015 retires compose as the dev orchestrator; leaving stale compose docs would
contradict the new single source of truth. 001's spec/plan stay as historical record, but its
runnable quickstart is updated to point at the new flow.

**Alternatives considered**: keeping compose as an optional fast path (rejected — the clarification
makes Kubernetes-only dev the standard; two orchestrators reintroduce the drift this feature removes).
