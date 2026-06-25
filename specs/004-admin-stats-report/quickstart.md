# Quickstart & Validation: Admin Account & Server-Wide Stats-Report

**Feature**: `004-admin-stats-report` | **Date**: 2026-06-22

A runnable guide to validate the feature end-to-end. Implementation details live in
[plan.md](./plan.md) / [data-model.md](./data-model.md) / [contracts/](./contracts/); this is the
**validation/run** guide. Commands use the inherited dev stack (kind cluster, `http://app.localhost`,
Mailpit) — see CLAUDE.md.

The **authoritative** validation is the test suite (§6). §§2–5 are a manual smoke that mirrors each user
story's Independent Test.

---

## 1. Prerequisites & bring-up

```bash
# From repo root. Brings up api + cpu worker + io worker + BEAT + postgres + rabbitmq + frontend + mailpit
scripts/up-dev.sh            # Windows: ./up-dev.ps1

# Admin credentials (dev defaults to admin@localhost / admin — refused outside dev).
# Override in deploy/k8s/overlays/dev/secret.env: ADMIN_EMAIL=..., ADMIN_PASSWORD=...
```

- App: `http://app.localhost` · Mailpit UI (dev mail catcher): the Mailpit Service from
  `overlays/dev/mailpit.yaml`.
- The `0003` migration (run by the migrate Job) adds `is_admin`, creates `stats_report_config` (30 d,
  enabled), and seeds the admin idempotently.
- The new **`beat`** Deployment (replicas = 1) fires the due-check tick every 60 s.

Smoke that the admin exists and is pre-verified:

```bash
ADMIN=admin@localhost; PW=admin
TOKEN=$(curl -s -X POST http://app.localhost/api/v1/auth/login \
  -d "username=$ADMIN&password=$PW" | jq -r .access_token)
test -n "$TOKEN" && echo "admin login OK (no verify step)"
```

---

## 2. User Story 1 — Admin & frequency control

```bash
A() { curl -s -H "Authorization: Bearer $TOKEN" "$@"; }

# Default is 30 days, enabled (FR-009 / Acceptance #2)
A http://app.localhost/api/v1/admin/stats-report/frequency
# => {"interval_seconds":2592000,"enabled":true}

# Set a valid interval >= 24h; it persists (FR-008 / Acceptance #3)
A -X POST http://app.localhost/api/v1/admin/stats-report/frequency \
  -H 'content-type: application/json' -d '{"interval_seconds":86400}'
A http://app.localhost/api/v1/admin/stats-report/frequency      # => 86400, enabled:true

# Below-minimum is rejected (422) and leaves the stored value unchanged (FR-008 / SC-002 / Acceptance #4)
A -X POST http://app.localhost/api/v1/admin/stats-report/frequency \
  -H 'content-type: application/json' -d '{"interval_seconds":3600}' -o /dev/null -w "%{http_code}\n"
# => 422 ; a subsequent GET still shows 86400

# Disable with 0 (FR-008 / Acceptance #5)
A -X POST http://app.localhost/api/v1/admin/stats-report/frequency \
  -H 'content-type: application/json' -d '{"interval_seconds":0}'   # => enabled:false

# Authorization boundary (FR-005 / Acceptance #6):
#  - register+verify+login an ordinary user, call the endpoint => 403
#  - call with no token => 401
curl -s -o /dev/null -w "%{http_code}\n" http://app.localhost/api/v1/admin/stats-report/frequency  # => 401
```

Persistence across restart (FR-006): set a value, `kubectl -n notification rollout restart deploy/postgres`
is **not** needed — the value lives in Postgres; restart the **api** (`kubectl -n notification rollout
restart deploy/notification-api`) and GET again — unchanged.

The admin behaving as an ordinary user with **no** cross-user access (FR-004) is covered by reusing 003's
ownership tests under the admin token (it is denied other users' resources exactly like any user).

---

## 3. User Story 3 — Seed the analytics dataset

Run the standalone seeder (bypasses the live pipeline; inserts completed sends + their `sent` transitions
across all 24 UTC hours and many dates):

```bash
# In-cluster (recommended — DB is inside kind): exec into the cpu worker (sync engine present)
kubectl -n notification exec deploy/notification-cpu-worker -- \
  python backend/scripts/seed.py --accounts 1000 --sends 500000

# Or on the host against a port-forwarded DB:
#   kubectl -n notification port-forward svc/postgres 5432:5432 &
#   cd backend && uv run python scripts/seed.py --accounts 1000 --sends 500000
```

Verify volume + spread (SC distribution, Acceptance #1/#2):

```sql
SELECT count(*) FROM user_account WHERE is_admin = false;             -- ~1000 (+1 admin)
SELECT count(*) FROM delivery_transition WHERE to_status = 'sent';    -- ~500000
SELECT extract(hour from at at time zone 'UTC')::int AS h, count(*)
FROM delivery_transition WHERE to_status='sent' GROUP BY h ORDER BY h; -- all 24 hours present
```

---

## 4. User Story 2 — Drive one report cycle (manual)

The API minimum cadence is 24 h, so manual validation **nudges the scheduling anchor into the past** (the
feature has no on-demand "send now" trigger by design — FR-011). With reporting enabled, push `anchor_at`
back so the next 60 s tick fires a cycle:

```sql
-- make it due now (keep interval enabled)
UPDATE stats_report_config SET interval_seconds = 86400, anchor_at = now() - interval '2 days';
```

Within ≤ 60 s the `beat` tick runs the cycle on the **cpu** worker (aggregate + render) and fans report
emails out on the **io** worker. Then check **Mailpit**:

- **Every account** received one email with a **24-bar PNG** of its own sends; a user with zero qualifying
  sends still got an **all-zero** graph (FR-015, SC-003).
- The **admin** received **two** emails — a personal graph and a **global** graph; the global bars equal
  the per-hour sums across all users, admin included (FR-016, SC-004/SC-005).
- Sends that never reached `sent` contributed **zero** (SC-006).
- Re-nudge the anchor and run a second cycle: the per-hour totals are **identical** — report sends are
  server-owned and excluded, no recursion (SC-009).
- Confirm the cycle **persisted** server-owned report rows (`user_id IS NULL`) that do **not** appear in
  any user's send-history (FR-019):

```sql
-- server-owned report sends exist (and grow each cycle) ...
SELECT count(*) FROM dispatch WHERE user_id IS NULL AND channel = 'report';
-- ... but they are invisible to users (GET /api/v1/sends for any user never lists them)
-- ... and excluded from the histogram (the §5 query filters user_id IS NOT NULL).
```

Disabled cadence (`interval_seconds = 0`) ⇒ the tick fires no cycle regardless of `anchor_at` (Acceptance
#7).

---

## 5. Cross-check the histogram against the data (SC-005)

Pick any seeded user id `:u` and compare the email's bars to:

```sql
SELECT extract(hour from dt.at at time zone 'UTC')::int AS h, count(*) AS sends
FROM delivery_transition dt
JOIN delivery dl ON dl.id = dt.delivery_id
JOIN dispatch d  ON d.id  = dl.dispatch_id
WHERE dt.to_status='sent' AND d.user_id = :u
GROUP BY h ORDER BY h;
```

The 24 bar heights must match exactly (missing hours = 0), and the bars sum to that user's total
qualifying sends.

---

## 6. Run the automated suite (authoritative)

```bash
# host (Testcontainers needs the Docker daemon — never run pytest inside a cluster pod)
cd backend
uv run pytest tests/unit/test_stats_config.py                         # interval validation, anchor reset
uv run pytest tests/unit/test_hour_histogram.py                       # 24-bucket bucketing
uv run pytest tests/unit/test_graph_renderer.py                       # matplotlib -> valid PNG
uv run pytest tests/integration/test_admin_frequency.py               # US1: authz + validation + persist
uv run pytest tests/integration/test_seed.py                          # US3: counts + 24h/multi-date spread
uv run pytest tests/integration/test_report_cycle.py                  # US2: real cpu+io cycle, per-scope buckets
uv run pytest tests/integration/test_report_resilience.py             # per-recipient failure isolation
uv run pytest                                                         # full suite (+ ruff, mypy in CI)
```

---

## 7. Success-criteria map

| SC | Where validated |
|----|-----------------|
| SC-001 admin reads/writes; non-admin/unauth refused | §2 + `test_admin_frequency.py` |
| SC-002 default 30 d; <24h rejected, unchanged | §2 + `test_admin_frequency.py` |
| SC-003 personal report for 100% of accounts; zero-send all-zero; failure isolated | §4 + `test_report_cycle.py`, `test_report_resilience.py` |
| SC-004 admin gets exactly two reports | §4 + `test_report_cycle.py` |
| SC-005 each scope's 24 counts match the data; bars sum to total | §5 + `test_report_cycle.py` |
| SC-006 never-`sent` excluded | §4 + `test_report_cycle.py` |
| SC-007 aggregation correct over ~500K | §3 + `test_seed.py` / `test_report_cycle.py` |
| SC-008 changed cadence next cycle; disable stops reports | §2/§4 + `test_admin_frequency.py` |
| SC-009 reporting changes no histogram (no recursion) | §4 + `test_report_cycle.py` |
| SC-010 no edits to existing channel adapters; one-time attachment capability | code review + `test_report_cycle.py` (new report `ChannelPort`) |
