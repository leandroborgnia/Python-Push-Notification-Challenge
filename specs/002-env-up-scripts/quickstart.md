# Quickstart & Validation: Environment Bring-Up

Runnable validation for feature **002-env-up-scripts**. Each scenario maps to an acceptance scenario
and Success Criterion. See [contracts/scripts-cli.md](./contracts/scripts-cli.md) and
[contracts/kustomize-overlays.md](./contracts/kustomize-overlays.md) for the precise contracts.

## Prerequisites

- **Linux/CI or WSL**: Docker, `kind`, `kubectl` on PATH. (Nothing else is installed on the host —
  `up-dev` manages the cluster + ingress controller.)
- **Windows**: WSL with a Linux distro that has the above on PATH; run the `.ps1` wrappers.
- No running cluster required for dev — `up-dev` creates the kind cluster if absent.
- `*.localhost` resolves to loopback in modern browsers; for other resolvers add
  `127.0.0.1 app.localhost api.localhost` to your hosts file.

---

## Scenario 1 — One-command dev bring-up (US1 #1/#2 · SC-001/002)

```sh
# Linux / CI / WSL:
scripts/up-dev.sh
# Windows:
./up-dev.ps1
```

**Expected**: kind cluster ensured → ingress-nginx Ready → api + frontend images built and
`kind load`ed → dev overlay applied → `migrate-<tag>` Job Complete → every Deployment rolled out.
Exit `0`. App reachable:

```sh
curl -fsS http://api.localhost/livez     # process liveness
curl -fsS http://api.localhost/readyz    # process + DB
curl -fsS http://api.localhost/health    # aggregate (DB + cpu/io workers)
# open http://app.localhost  → frontend renders /health
```

---

## Scenario 2 — Idempotent re-run (US1 #3 · FR-011)

```sh
scripts/up-dev.sh && scripts/up-dev.sh   # run twice
```

**Expected**: the second run converges via declarative apply — no duplicated/recreated resources, no
errors, still exits `0`. (Same image tag ⇒ the `migrate-<tag>` Job is unchanged/no-op.)

---

## Scenario 3 — Run from a subdirectory (SC-008 · FR-007)

```sh
( cd backend && ../scripts/up-dev.sh )
```

**Expected**: identical behaviour to running from the repo root (the script resolves the repo root
itself).

---

## Scenario 4 — Prod bring-up & fail-fast (US2 · SC-003 · FR-016)

```sh
# Happy path (configured prod context + registry + secret present):
IMAGE_REGISTRY=registry.example.com KUBE_CONTEXT=prod scripts/up-prod.sh   # → applies, waits, exit 0

# Missing managed-datastore secret → must fail fast, no partial apply:
kubectl --context prod -n notification delete secret notification-secrets   # simulate absence
IMAGE_REGISTRY=registry.example.com KUBE_CONTEXT=prod scripts/up-prod.sh   # → clear error, exit ≠0
```

**Expected**: happy path reports rollout success via exit `0`; the missing-secret case prints an
actionable message and exits non-zero **before** applying app workloads. Each fail-fast case (missing
secret / unreachable context / missing prerequisite) errors and exits non-zero **within ~10s**
(SC-005) — e.g. wrap the call in `time …` and confirm there is no hang.

---

## Scenario 5 — Wrapper exit-code propagation (US3 #1/#2/#3 · SC-004)

```powershell
# Force a failure in the bash script (e.g. unreachable context) through the wrapper:
$env:KUBE_CONTEXT = "does-not-exist"
./up-dev.ps1 --some-extra-arg
echo "exit=$LASTEXITCODE"   # MUST be the same non-zero code the .sh returned
```

**Inspect** `up-dev.ps1` / `up-prod.ps1`: they contain only the `wsl.exe` invocation + `exit
$LASTEXITCODE` (no orchestration logic), and `--some-extra-arg` is forwarded to the bash script.

---

## Scenario 6 — Runtime image carries no build toolchain (SC-006 · FR-013)

```sh
docker build -t notification-service:probe ./backend
docker run --rm --entrypoint sh notification-service:probe -c 'command -v uv && echo HAS_UV || echo NO_UV'
docker image inspect notification-service:probe --format '{{.Size}}'
```

**Expected**: prints `NO_UV` — the authoritative check that the runtime stage carries no build tools;
the size is consequently smaller than a single-stage build.

---

## Scenario 7 — Migrations run once per deploy (SC-007 · FR-014)

```sh
scripts/up-dev.sh
kubectl -n notification get jobs        # exactly one migrate-<tag> Job, Complete
kubectl -n notification get pods -l app=notification-api -o jsonpath='{.items[*].spec.initContainers[*].name}'
# → await-migrations  (the API init container WAITS; it does not run alembic)
```

**Expected**: one migration Job per deploy regardless of API replica count; API pods only wait.

---

## Scenario 8 — LF line endings guard (FR-010 · edge case)

```sh
file scripts/up-dev.sh scripts/up-prod.sh   # must report "ASCII text", NOT "with CRLF line terminators"
git check-attr text eol -- scripts/up-dev.sh # → text: set, eol: lf
```

**Expected**: `.sh` files are LF even on a Windows checkout, so they execute under WSL/bash.

---

## Success-criteria coverage

| SC | Scenario |
|---|---|
| SC-001 dev to Ready, one command | 1 |
| SC-002 same script on Linux/CI | 1 (parity is by-design — one bash source of truth; run Scenario 1 unchanged on Linux/CI) |
| SC-003 prod rollout via exit code | 4 |
| SC-004 100% logic in bash; thin wrappers | 5 |
| SC-005 fail-fast <10s on missing prereq | 4, 5 |
| SC-006 runtime image has no build tools | 6 |
| SC-007 migrations once per deploy | 7 |
| SC-008 run from subdirectory | 3 |
