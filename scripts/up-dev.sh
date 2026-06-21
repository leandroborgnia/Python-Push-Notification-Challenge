#!/usr/bin/env bash
#
# up-dev.sh — one-command DEV bring-up on a local kind cluster (US1 · the MVP).
#
# Builds the app + frontend images, ensures a kind cluster with ingress-nginx, loads the
# images, applies the dev overlay, and waits for every workload to become Ready. This bash
# file is the canonical source of truth; up-dev.ps1 is a thin WSL wrapper around it.
#
# Usage:  scripts/up-dev.sh [extra args forwarded to `kubectl apply`]
# Env:    KIND_CLUSTER_NAME (default `notification`), ROLLOUT_TIMEOUT (default 180s).
set -euo pipefail

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=scripts/lib/common.sh
. "${SCRIPT_DIR}/lib/common.sh"

# Operate from the repo root regardless of CWD (FR-007, SC-008).
cd "$(repo_root)"

# --- configuration --------------------------------------------------------
NAMESPACE=notification
KIND_CLUSTER_NAME="${KIND_CLUSTER_NAME:-notification}"
APP_HOST=app.localhost
API_HOST=api.localhost
# ingress-nginx pinned to an explicit released tag (Principle I) — never main/latest. The kind
# provider manifest already digest-pins the controller image.
INGRESS_NGINX_REF=controller-v1.15.1
INGRESS_NGINX_MANIFEST="https://raw.githubusercontent.com/kubernetes/ingress-nginx/${INGRESS_NGINX_REF}/deploy/static/provider/kind/deploy.yaml"

# --- prerequisites (fail fast, <10s — SC-005) -----------------------------
require_cmd docker kind kubectl

# --- ensure the kind cluster (idempotent — FR-011) ------------------------
if kind get clusters 2>/dev/null | grep -qx "$KIND_CLUSTER_NAME"; then
  log "kind cluster '${KIND_CLUSTER_NAME}' already exists — reusing."
else
  log "creating kind cluster '${KIND_CLUSTER_NAME}' (host :80/:443 → ingress)..."
  kind create cluster --name "$KIND_CLUSTER_NAME" --config deploy/k8s/kind-config.yaml
fi
kubectl config use-context "kind-${KIND_CLUSTER_NAME}" >/dev/null

# --- ensure ingress-nginx (idempotent) ------------------------------------
log "ensuring ingress-nginx (${INGRESS_NGINX_REF})..."
kubectl apply -f "$INGRESS_NGINX_MANIFEST"
log "waiting for the ingress-nginx controller to roll out..."
kubectl -n ingress-nginx rollout status deploy/ingress-nginx-controller \
  --timeout="${ROLLOUT_TIMEOUT:-180s}" || die "ingress-nginx controller did not become Ready."

# --- derive the per-run image tag + refs (never :latest — FR-018) ---------
IMAGE_TAG="$(image_tag dev)"; export IMAGE_TAG
API_IMAGE="notification-service:${IMAGE_TAG}"
FRONTEND_IMAGE="notification-frontend:${IMAGE_TAG}"
export API_IMAGE FRONTEND_IMAGE
log "image tag: ${IMAGE_TAG}"

# --- build the images (a build failure aborts before any apply) -----------
log "building ${API_IMAGE}..."
docker build -t "$API_IMAGE" ./backend
log "building ${FRONTEND_IMAGE} (VITE_API_BASE_URL=http://${API_HOST})..."
docker build -t "$FRONTEND_IMAGE" --build-arg "VITE_API_BASE_URL=http://${API_HOST}" ./frontend

# --- load images into kind (no registry in dev) ---------------------------
log "loading images into kind cluster '${KIND_CLUSTER_NAME}'..."
kind load docker-image "$API_IMAGE" --name "$KIND_CLUSTER_NAME"
kind load docker-image "$FRONTEND_IMAGE" --name "$KIND_CLUSTER_NAME"

# --- ensure the dev secret source (gitignored; no creds in git) -----------
if [ ! -f deploy/k8s/overlays/dev/secret.env ]; then
  log "creating deploy/k8s/overlays/dev/secret.env from secret.env.example (gitignored)..."
  cp deploy/k8s/overlays/dev/secret.env.example deploy/k8s/overlays/dev/secret.env
fi

# --- render + apply the dev overlay (declarative, idempotent) -------------
log "applying the dev overlay..."
render_apply dev "$@"

# --- wait for migrations, then every workload -----------------------------
log "waiting for the migrate Job ($(migrate_job_name)) to complete..."
kubectl -n "$NAMESPACE" wait --for=condition=complete "job/$(migrate_job_name)" \
  --timeout="${ROLLOUT_TIMEOUT:-180s}" || die "migration Job did not complete: $(migrate_job_name)"

wait_rollout "$NAMESPACE" \
  deploy/notification-api \
  deploy/cpu-worker \
  deploy/io-worker \
  deploy/frontend \
  deploy/postgres \
  deploy/rabbitmq

log "✅ dev stack is Ready."
log "    app : http://${APP_HOST}"
log "    api : http://${API_HOST}/health"
