# Contract: Kustomize Overlays

Fixes what `kubectl kustomize deploy/k8s/overlays/<env>` MUST render, so the bring-up scripts and the
manifests can be developed independently and verified against each other (`kubectl kustomize … |
kubectl apply --dry-run=client -f -`).

## Layout (FR-017)

```text
deploy/k8s/
  base/                       # API + cpu/io workers + frontend + migrate Job + Ingress + Namespace
  overlays/dev/               # + Postgres + RabbitMQ + dev Secret + dev hosts; replicas=1
  overlays/prod/              # managed-datastore config; replicas=N; prod hosts; no datastores/secret
```

No tooling beyond `kubectl` (built-in kustomize). Deploy = `kubectl kustomize overlays/<env>` →
substitute image placeholders → `kubectl apply -f -` (FR-017, see [research.md](../research.md) R3).

## `base` MUST contain

- `Namespace/notification`.
- `Deployment/notification-api` — single `uvicorn` container (one process/pod), `livenessProbe`
  `/livez`, `readinessProbe` `/readyz`, env from `notification-secrets`, and an **`await-migrations`
  init container** that blocks on `alembic current == head` (no DDL). Image `__API_IMAGE__`.
- `Service/notification-api` — ClusterIP 80 → 8000.
- `Deployment/cpu-worker` — `celery … --pool=prefork -n cpu@%h -Q cpu`. Image `__API_IMAGE__`.
- `Deployment/io-worker` — `celery … --pool=threads -n io@%h -Q io`. Image `__API_IMAGE__`.
- `Deployment/frontend` + `Service/frontend` — nginx serving the SPA. Image `__FRONTEND_IMAGE__`.
- `Job/migrate-<tag>` — `alembic upgrade head`, `backoffLimit`, `ttlSecondsAfterFinished`,
  env from `notification-secrets`. Image `__API_IMAGE__`. The base name uses a **DNS-1123-valid**
  placeholder token (lowercase) the script replaces with the sanitized per-run tag — so the
  un-substituted base still validates under `kubeconform`/`--dry-run`.
- `Ingress/notification` — two host rules (app host → `frontend`, api host → `notification-api`),
  hostnames patched by the overlay.

Workload images reference the substitution placeholders (`__API_IMAGE__`, `__FRONTEND_IMAGE__`, in
string `image:` fields) and the Job name embeds the per-run tag via a DNS-valid placeholder — **never**
a floating tag (FR-018, Principle I).

## `overlays/dev` MUST add / set

- `secretGenerator` → `notification-secrets` sourced from a **gitignored `secret.env`** (created by
  `up-dev` from a committed `secret.env.example` template — in-cluster Service DNS, `app/app`,
  `guest/guest` placeholders). No credential values are committed (Principle VI; contract K6).
- `Deployment+Service/postgres` (`postgres:16.14-alpine`, `emptyDir`).
- `Deployment+Service/rabbitmq` (`rabbitmq:4.3.2-management`) + `ConfigMap` for `permit-deprecated.conf`.
- Ingress host patch → `app.localhost` / `api.localhost`.
- `replicas: 1` for api/workers/frontend.

## `overlays/prod` MUST set (and MUST NOT add)

- Image `newName` = `${IMAGE_REGISTRY}/…` (registry-qualified), `newTag` = per-run `<sha>`.
- `replicas: N` for api/workers/frontend.
- Ingress host patch → configured prod hostnames.
- **MUST NOT** define Postgres/RabbitMQ or the `notification-secrets` Secret — prod consumes an
  externally-managed Secret with managed-datastore URLs (FR-016; `up-prod` preflights it).

## Invariants

| ID | Invariant |
|---|---|
| K1 | `dev` and `prod` differ **only** by overlay (images, replicas, datastores, ingress hosts, secret source). |
| K2 | No manifest references `:latest` or a minor-only image tag (FR-018, Principle I). |
| K3 | Both overlays render valid manifests under `kubectl apply --dry-run=client`, and **base resource names (incl. the migrate Job) are DNS-1123-valid even un-substituted** so `kubeconform` passes. |
| K4 | The API never migrates at startup; migration is solely the `migrate-<tag>` Job (FR-014). |
| K5 | prod renders **no** in-cluster datastore and **no** committed Secret (FR-016, Principle VI). |
| K6 | No credential **values** are committed: the dev `secretGenerator` reads a gitignored `secret.env`; only `secret.env.example` (placeholders) is tracked (Principle VI; finding C1). |
