# Contract: Bring-Up Script CLI

The interfaces this feature exposes are **command-line entrypoints**. This contract fixes their
synopsis, inputs, behaviour, and exit codes so US1–US3 acceptance scenarios are testable.

## Entrypoints

| Entrypoint | Path | Role |
|---|---|---|
| `up-dev.sh` | `scripts/up-dev.sh` | Canonical dev bring-up (kind). Source of truth. |
| `up-prod.sh` | `scripts/up-prod.sh` | Canonical prod bring-up (prod context). Source of truth. |
| `up-dev.ps1` | `up-dev.ps1` (repo root) | Thin Windows wrapper → `wsl.exe bash ./scripts/up-dev.sh "$@"`. |
| `up-prod.ps1` | `up-prod.ps1` (repo root) | Thin Windows wrapper → `wsl.exe bash ./scripts/up-prod.sh "$@"`. |

## Synopsis

```text
scripts/up-dev.sh   [extra args forwarded to kubectl apply]
scripts/up-prod.sh  [extra args forwarded to kubectl apply]
./up-dev.ps1        [args...]      # forwarded verbatim to up-dev.sh via WSL
./up-prod.ps1       [args...]      # forwarded verbatim to up-prod.sh via WSL
```

## Inputs (environment)

| Variable | Scripts | Required | Default | Meaning |
|---|---|---|---|---|
| `KUBE_CONTEXT` | both | no | current context | Target cluster context. |
| `IMAGE_REGISTRY` | `up-prod` | **yes** | — | Registry to push images to / reference in prod manifests. |
| `KIND_CLUSTER_NAME` | `up-dev` | no | `notification` | Name of the local kind cluster. |
| `ROLLOUT_TIMEOUT` | both | no | e.g. `180s` | Per-workload `rollout status` / Job `wait` timeout. |

Positional args are **forwarded unchanged** to the underlying `kubectl apply` (FR-006). The `.ps1`
wrappers forward all args to the `.sh` (FR-006, US3#2) and contain **no other logic** (FR-005, SC-004).

## Behaviour contract

| ID | Guarantee | Source |
|---|---|---|
| C1 | Runs identically regardless of CWD (operates on repo root). | FR-007, SC-008 |
| C2 | `up-dev` builds images, ensures the kind cluster + ingress-nginx, loads images, applies the **dev** overlay, and waits for every workload Ready. | FR-001/012/018/019/020, US1 |
| C3 | `up-prod` builds + pushes images and applies the **prod** overlay against the existing prod context; never creates/destroys a cluster. | FR-002/018/020, US2 |
| C4 | Re-running is idempotent (declarative apply; no duplicate/corrupt state). | FR-011, US1#3 |
| C5 | Migrations run once per deploy via the `migrate-<tag>` Job; the script waits on it. | FR-014, SC-007 |
| C6 | Each `.ps1` is a thin wrapper: only the `wsl.exe` call + arg/exit-code passthrough. | FR-005, SC-004, US3#1 |

## Exit codes

| Code | Condition |
|---|---|
| `0` | All workloads reached Ready / rollout succeeded (FR-008, SC-001/003). |
| `≠0` | Any prerequisite missing, build/push failure, unreachable/wrong context, missing prod secret, migration Job failure, or a workload that did not become Ready. |

The `.ps1` wrappers MUST return the **same** non-zero code the `.sh` returned (`exit $LASTEXITCODE`) —
failures are never masked (FR-006, US3#3).

## Fail-fast preconditions (clear message + `≠0`, within ~10s — SC-005, FR-009)

| Precondition | Checked by | On failure |
|---|---|---|
| `wsl.exe` available | `.ps1` wrappers | Actionable message, non-zero (edge: WSL not installed). |
| `docker` / `kind` / `kubectl` on PATH | `up-dev` | Names the missing tool; exits non-zero before any apply. |
| `kubectl` + reachable target context | both | Refuses to apply to a wrong/unreachable cluster. |
| `IMAGE_REGISTRY` set | `up-prod` | Refuses to build/push without a target registry. |
| `notification-secrets` present in target ns | `up-prod` | Refuses to deploy an app that can't reach its managed data layer (no in-cluster fallback). |
| Image build succeeds | both | Stops before applying manifests. |

## Acceptance-scenario mapping

- **US1 #1/#2** → C2 on Windows (`up-dev.ps1`) and Linux/CI (`up-dev.sh`).
- **US1 #3** → C4 (idempotent re-run).
- **US2 #1** → C3 (prod apply + rollout success). **US2 #2** → fail-fast on bad context.
- **US3 #1** → C6 (wrappers carry no logic). **US3 #2** → arg passthrough. **US3 #3** → exit-code propagation.
