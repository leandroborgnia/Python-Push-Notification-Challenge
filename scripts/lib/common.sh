# shellcheck shell=bash
#
# Shared library for the bring-up scripts (scripts/up-dev.sh, scripts/up-prod.sh).
# SOURCED, never executed directly. Provides: repo-root resolution, structured logging,
# fail-fast prereq checks, per-run image-tag derivation, and the render-apply / rollout-wait
# helpers. Keeping the logic here single-sources the behaviour both scripts (and the .ps1
# wrappers, via WSL) run (research R5).

# --- PATH: include per-user bin dirs (FR-009, SC-005) ---------------------
# Per-user tools (e.g. `kind`, `kubectl` under ~/.local/bin or ~/bin) are put on PATH by
# ~/.profile, which only runs in *login* shells. The .ps1 wrappers invoke this through
# `wsl.exe bash <script>` — a NON-login shell — so those dirs are absent and require_cmd
# fails even when the tool is installed. Re-add them here (idempotent, source-time) so the
# prereq check sees the same tools the user has interactively, however the shell was launched.
for _user_bin in "$HOME/.local/bin" "$HOME/bin"; do
  case ":${PATH}:" in
    *":${_user_bin}:"*) : ;;                                  # already on PATH
    *) [ -d "$_user_bin" ] && PATH="${_user_bin}:${PATH}" ;;  # prepend only if it exists
  esac
done
unset _user_bin
export PATH

# --- repo root (FR-007, SC-008) -------------------------------------------
# Resolve the repo root from any CWD: prefer git, fall back to walking up from this file so it
# still works in a checkout without git metadata.
repo_root() {
  local root
  if root=$(git rev-parse --show-toplevel 2>/dev/null); then
    printf '%s\n' "$root"
    return 0
  fi
  # Fallback: this file lives at <root>/scripts/lib/common.sh → root is two levels up.
  ( CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd )
}

# --- structured logging ----------------------------------------------------
log()  { printf '\033[1;34m[up]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m[up:warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[up:error]\033[0m %s\n' "$*" >&2; exit 1; }

# --- fail-fast prerequisite checks (FR-009, SC-005) -----------------------
require_cmd() {
  local missing=0 cmd
  for cmd in "$@"; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      warn "required command not found on PATH: $cmd"
      missing=1
    fi
  done
  [ "$missing" -eq 0 ] || die "install the missing prerequisite(s) above and re-run."
}

# --- per-run image tag (FR-018, Principle I; research R3) -----------------
# dev : dev-<sha>, plus -dirty-<epoch> when the tree is dirty (dev rebuilds against WIP).
# prod: bare <sha>, and refuses a dirty tree (immutable, reproducible). Never `latest`.
git_short_sha() {
  git rev-parse --short HEAD 2>/dev/null || die "not a git repository (cannot derive image tag)."
}

tree_is_dirty() { [ -n "$(git status --porcelain 2>/dev/null)" ]; }

image_tag() {
  local env="$1" sha
  sha=$(git_short_sha)
  case "$env" in
    dev)
      if tree_is_dirty; then
        printf 'dev-%s-dirty-%s\n' "$sha" "$(date +%s)"
      else
        printf 'dev-%s\n' "$sha"
      fi
      ;;
    prod)
      tree_is_dirty && die "prod images require a clean working tree; commit or stash changes first."
      printf '%s\n' "$sha"
      ;;
    *) die "image_tag: unknown environment '$env'" ;;
  esac
}

# Sanitize a value to a DNS-1123 label (lowercase alnum + '-') for use in a resource name.
dns_label() {
  printf '%s' "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -e 's/[^a-z0-9-]/-/g' -e 's/^-*//' -e 's/-*$//'
}

# The migrate Job's per-run name (matches the base manifest's DNS-valid sentinel).
# Requires IMAGE_TAG to be set by the caller.
migrate_job_name() { printf 'migrate-%s\n' "$(dns_label "$IMAGE_TAG")"; }

# --- render + apply (FR-011, FR-017, FR-018; research R3) ------------------
# Render the overlay with kubectl's BUILT-IN kustomize, substitute the per-run image refs and
# migrate-Job tag, then declaratively apply (idempotent). Extra positional args are forwarded
# verbatim to `kubectl apply` (FR-006). Requires API_IMAGE, FRONTEND_IMAGE, IMAGE_TAG exported.
render_apply() {
  local env="$1"; shift
  local tag_dns
  tag_dns=$(dns_label "$IMAGE_TAG")
  kubectl kustomize "deploy/k8s/overlays/${env}" \
    | sed -e "s|__API_IMAGE__|${API_IMAGE}|g" \
          -e "s|__FRONTEND_IMAGE__|${FRONTEND_IMAGE}|g" \
          -e "s|migrate-imagetagslot|migrate-${tag_dns}|g" \
    | kubectl apply -f - "$@"
}

# --- cluster reachability wait --------------------------------------------
# Poll until the given kube-context's API server answers, or <timeout> seconds elapse.
# Used to confirm a freshly (re)started kind node container is actually serving before we
# start applying manifests against it. Returns non-zero on timeout.
wait_api_reachable() {
  local ctx="$1" timeout="${2:-90}" waited=0
  while [ "$waited" -lt "$timeout" ]; do
    if kubectl --context "$ctx" cluster-info --request-timeout=5s >/dev/null 2>&1; then
      return 0
    fi
    sleep 3
    waited=$((waited + 3))
  done
  return 1
}

# --- rollout wait (FR-008, FR-012, SC-003) --------------------------------
# Wait for each named workload (e.g. deploy/notification-api) to become Ready, honoring
# ROLLOUT_TIMEOUT (default 180s). Any failure exits non-zero and names the workload.
wait_rollout() {
  local ns="$1"; shift
  local timeout="${ROLLOUT_TIMEOUT:-180s}" workload
  for workload in "$@"; do
    log "waiting for rollout: ${workload} (timeout ${timeout})"
    kubectl -n "$ns" rollout status "$workload" --timeout="$timeout" \
      || die "rollout did not complete: ${workload}"
  done
}
