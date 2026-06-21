# Feature Specification: Environment Bring-Up Scripts (up-dev / up-prod)

**Feature Branch**: `002-env-up-scripts`

**Created**: 2026-06-21

**Status**: Draft

**Input**: User description: "we need 2 sh scripts, up-dev and up-prod that switch on each environment, also 2 more ps1 scripts up-dev and up-prod that call their respective up-xxx.sh through wsl.exe"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One-command dev bring-up (Priority: P1)

As a developer, I can start the entire **dev** environment with a single command and have every
service come up healthy — without remembering the underlying orchestration commands.

**Why this priority**: Day-to-day work depends on a fast, reliable, memorable way to start the local
stack. This is the script most people run most often, so it delivers the most value first.

**Independent Test**: From a clean checkout, run the dev bring-up entrypoint (the `.ps1` on Windows or
the `.sh` directly on Linux) and confirm every service reaches a healthy state with no manual steps.

**Acceptance Scenarios**:

1. **Given** a clean checkout on Windows, **When** the developer runs `up-dev.ps1`, **Then** the full
   local dev stack starts and every service reports healthy, with no additional manual commands.
2. **Given** a clean checkout on Linux/CI, **When** the developer runs `scripts/up-dev.sh`, **Then**
   the same stack comes up with identical behavior.
3. **Given** the dev stack is already running, **When** the script is run again, **Then** it completes
   safely (idempotent) without corrupting the running environment.

---

### User Story 2 - One-command prod bring-up (Priority: P2)

As an operator/developer, I can bring up the **prod** environment with a single command that targets
the production deployment path (not the local container stack).

**Why this priority**: A matching prod entrypoint gives parity with dev and a single, documented way
to stand up the production topology; it is used less often than dev, hence P2.

**Independent Test**: Run the prod bring-up entrypoint against a configured target and confirm it
applies the production topology and reports success or failure via its exit code.

**Acceptance Scenarios**:

1. **Given** a configured production target, **When** the operator runs `up-prod.ps1` (or
   `scripts/up-prod.sh`), **Then** the production deployment is applied and the command reports success.
2. **Given** the production target is unreachable/misconfigured, **When** the script runs, **Then** it
   fails fast with a clear message and a non-zero exit code (it does not partially proceed silently).

---

### User Story 3 - Windows → WSL parity (thin wrappers, one source of truth) (Priority: P3)

As a developer on Windows, I can run the same logic my Linux/CI/container teammates run, because the
PowerShell entrypoints are **thin wrappers** that invoke the canonical bash scripts through `wsl.exe`.

**Why this priority**: Single-sourcing the logic in bash guarantees the behavior I test on Windows is
the behavior that runs in CI, containers, and prod (all Linux). It is a correctness/maintainability
property layered on top of US1/US2.

**Independent Test**: Inspect the wrappers (they contain only the WSL invocation, no orchestration
logic), then confirm arguments pass through and the bash script's exit code is propagated back to
PowerShell.

**Acceptance Scenarios**:

1. **Given** `up-dev.ps1`/`up-prod.ps1`, **When** they are reviewed, **Then** they contain no
   orchestration logic — only the `wsl.exe` call to the matching `.sh` — so logic exists in exactly one
   place.
2. **Given** a wrapper is invoked with extra arguments, **When** it runs, **Then** those arguments are
   forwarded unchanged to the bash script.
3. **Given** the bash script exits non-zero, **When** the wrapper finishes, **Then** PowerShell also
   returns that non-zero exit code (failures are not masked).

---

### Edge Cases

- **WSL not installed/configured** on Windows → the `.ps1` wrapper fails fast with an actionable
  message (how to enable WSL), non-zero exit.
- **Docker daemon not running** → `up-dev` fails fast with a clear message rather than hanging.
- **Cluster/kubeconfig unreachable** → `up-prod` fails fast with a clear message, non-zero exit.
- **Script invoked from a subdirectory** → it still operates against the repository root, not the
  caller's current directory.
- **Windows line endings (CRLF)** on the `.sh` files → would break execution under WSL/bash; the bash
  scripts MUST remain LF so a Windows checkout still runs them correctly.
- **Re-run while already up** → safe/idempotent; no duplicate or corrupted state.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The project MUST provide an executable `up-dev` bash script that brings up the complete
  local **dev** environment in a single command.
- **FR-002**: The project MUST provide an executable `up-prod` bash script that brings up/deploys the
  **prod** environment in a single command.
- **FR-003**: Each script MUST target its environment's orchestration and apply environment-appropriate
  configuration — dev uses the local container stack; prod uses the production deployment path.
- **FR-004**: The project MUST provide `up-dev.ps1` and `up-prod.ps1` Windows entrypoints that invoke
  their corresponding bash script via `wsl.exe`.
- **FR-005**: The PowerShell entrypoints MUST be **thin wrappers** containing no orchestration logic;
  all logic lives in the bash scripts (single source of truth → dev/CI/container/prod parity).
- **FR-006**: The wrappers MUST forward any passed arguments to the bash script and MUST propagate the
  bash script's exit code back to the caller.
- **FR-007**: Every script MUST operate against the repository root regardless of the caller's current
  working directory.
- **FR-008**: Every script MUST exit `0` on success and non-zero on failure, so it is usable in
  automation/CI.
- **FR-009**: Every script MUST fail fast with a clear, actionable message when a required prerequisite
  is missing (Docker for dev; WSL for the wrappers; reachable cluster/kubeconfig for prod).
- **FR-010**: The bash scripts MUST use LF line endings (enforced via repository configuration, e.g.
  `.gitattributes`) so they execute correctly under WSL/Linux even on a Windows checkout.
- **FR-011**: Re-running a script MUST be safe (idempotent): bringing an already-up environment up
  again MUST NOT corrupt or duplicate state.
- **FR-012**: The dev script MUST surface readiness — report that the stack reached a healthy state, or
  report which service failed.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From a clean checkout on Windows, a developer brings the full dev stack to healthy with a
  single command and zero manual follow-up steps.
- **SC-002**: The same dev bash script runs unchanged on Linux/CI and yields the same result (parity).
- **SC-003**: `up-prod` applies the production topology and reports success/failure via its exit code in
  100% of runs.
- **SC-004**: 100% of orchestration logic resides in the bash scripts; each PowerShell wrapper contains
  only the WSL invocation (a handful of lines, no environment logic).
- **SC-005**: A missing prerequisite produces a clear error and a non-zero exit within 10 seconds (no
  hanging).
- **SC-006**: Running any script from a subdirectory behaves identically to running it from the repo
  root.

## Assumptions

- **"dev environment"** = the project's documented local container stack (today: `docker compose up`).
- **"prod environment"** = the project's Kubernetes deployment; `up-prod` applies the existing
  `deploy/k8s/` manifests to the currently-configured cluster context (consistent with the
  constitution's prod = Kubernetes). *This is the one assumption worth confirming — the alternative
  reading is "run a production-like stack locally"; resolve via `/speckit.clarify` if that's intended.*
- Windows developers have **WSL with a Linux distribution + bash** available; the wrappers target
  `wsl.exe`. Docker (dev) and a reachable cluster/kubeconfig (prod) are **prerequisites**, not
  provisioned by these scripts.
- Script layout matches the requested shape — bash scripts under `scripts/` and PowerShell wrappers at
  the repository root (`up-dev.ps1` → `wsl.exe bash ./scripts/up-dev.sh`); exact paths finalized in
  planning.
- This feature aligns with the constitution's Operations environments (dev = Docker, prod = Kubernetes);
  the "bash-canonical + thin PowerShell wrapper" convention is new and may optionally be ratified into
  the constitution separately.

## Out of Scope

- Provisioning Docker, WSL, or the Kubernetes cluster themselves.
- Changes to the CI/CD pipeline (GitHub Actions already builds/deploys prod; these are
  developer/operator-invoked local entrypoints).
- Environments other than `dev` and `prod`.
- Tear-down / `down` scripts (only bring-up is requested).
- Application code, migration contents, or the analytics seed script.
