#!/usr/bin/env bash
#
# up-prod.sh — one-command PROD bring-up against the EXISTING production cluster (US2).
#
# Builds + pushes the app + frontend images to ${IMAGE_REGISTRY} and applies the prod overlay
# (app-only — managed external datastores). NEVER creates or destroys a cluster. Fails fast with
# no partial apply if the target context is unreachable or the managed-datastore Secret is
# absent. Exit code reflects rollout success. Canonical source of truth; up-prod.ps1 wraps it.
#
# Usage:  scripts/up-prod.sh [extra args forwarded to `kubectl apply`]
# Env:    IMAGE_REGISTRY (required), KUBE_CONTEXT (optional), VITE_API_BASE_URL (optional),
#         ROLLOUT_TIMEOUT (default 180s).
set -euo pipefail

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=scripts/lib/common.sh
. "${SCRIPT_DIR}/lib/common.sh"

# Operate from the repo root regardless of CWD (FR-007, SC-008).
cd "$(repo_root)"

NAMESPACE=notification

# --- prerequisites + required config (fail fast, <10s — SC-005) -----------
require_cmd docker kubectl git
[ -n "${IMAGE_REGISTRY:-}" ] \
  || die "IMAGE_REGISTRY is required (registry to push images to / reference in prod manifests)."

# Select the target context if given; otherwise use the current one. Never create a cluster.
if [ -n "${KUBE_CONTEXT:-}" ]; then
  kubectl config use-context "$KUBE_CONTEXT" >/dev/null \
    || die "cannot select kube context '${KUBE_CONTEXT}'."
fi
CONTEXT=$(kubectl config current-context 2>/dev/null) || die "no current kube context is set."
log "target context: ${CONTEXT}"

# --- preflight: reachable context + managed-datastore Secret (no apply yet) ----
log "preflighting cluster reachability..."
kubectl cluster-info >/dev/null 2>&1 \
  || die "target cluster is unreachable (context '${CONTEXT}'). Aborting before any apply."
log "preflighting that notification-secrets exists in namespace '${NAMESPACE}'..."
kubectl -n "$NAMESPACE" get secret notification-secrets >/dev/null 2>&1 \
  || die "Secret 'notification-secrets' not found in namespace '${NAMESPACE}'. prod consumes a managed-datastore Secret (no in-cluster fallback). Aborting before any apply."

# --- require a clean tree, derive the immutable per-run tag ----------------
IMAGE_TAG="$(image_tag prod)"; export IMAGE_TAG   # refuses a dirty tree
API_IMAGE="${IMAGE_REGISTRY%/}/notification-service:${IMAGE_TAG}"
FRONTEND_IMAGE="${IMAGE_REGISTRY%/}/notification-frontend:${IMAGE_TAG}"
export API_IMAGE FRONTEND_IMAGE
log "image tag: ${IMAGE_TAG}"

# --- build + push (a build/push failure aborts before any apply) -----------
log "building + pushing ${API_IMAGE}..."
docker build -t "$API_IMAGE" ./backend
docker push "$API_IMAGE"
log "building + pushing ${FRONTEND_IMAGE}..."
docker build -t "$FRONTEND_IMAGE" \
  --build-arg "VITE_API_BASE_URL=${VITE_API_BASE_URL:-https://api.notification.example.com}" ./frontend
docker push "$FRONTEND_IMAGE"

# --- render + apply the prod overlay (declarative, idempotent) -------------
log "applying the prod overlay..."
render_apply prod "$@"

# --- wait for migrations, then rollout (exit code = rollout success) -------
log "waiting for the migrate Job ($(migrate_job_name)) to complete..."
kubectl -n "$NAMESPACE" wait --for=condition=complete "job/$(migrate_job_name)" \
  --timeout="${ROLLOUT_TIMEOUT:-180s}" || die "migration Job did not complete: $(migrate_job_name)"

wait_rollout "$NAMESPACE" \
  deploy/notification-api \
  deploy/cpu-worker \
  deploy/io-worker \
  deploy/frontend

log "✅ prod rollout complete (context ${CONTEXT})."
