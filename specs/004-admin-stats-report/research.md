# Research: Admin Account & Server-Wide Stats-Report

**Feature**: `004-admin-stats-report` | **Date**: 2026-06-22

This records the plan-level decisions the spec deferred to planning (resolved with the user 2026-06-22),
plus the supporting design choices that follow from the inherited constitution + 003 foundation. The
spec's ten Clarifications (Session 2026-06-22) already fixed the behavioural semantics and are not
re-litigated here.

---

## 1. Report email delivery — a new report `ChannelPort` adapter reusing the resilient pipeline

**Decision**: Add the report email as **one new `ChannelPort` adapter** (`Channel.REPORT`,
`adapters/channels/report_email/`, `SmtpReportEmailChannel`) — a **synchronous** stdlib-`smtplib` sender
that attaches the rendered PNG and points at the per-environment SMTP host (dev → the existing Mailpit
catcher). Report sends run through the **existing resilient delivery pipeline** (`DeliveryService` on the
`io`/threads pool): retry/backoff + per-destination circuit breaker + idempotency + the persisted
`queued → sent → delivered | failed` lifecycle, and are **persisted** as `dispatch`/`delivery` rows. The
sends are **server-originated** (`dispatch.user_id = NULL`), so they are excluded from aggregation and from
every user's send-history. To carry the graph, the shared `Payload` gains an **optional attachment** (a
one-time capability extension; existing adapters ignore it). It is deliberately the seed of the future
**real (non-simulated) email channel**.

**Rationale**:
- **Full resilience by reuse (Principle IV)** — reports are real sends and deserve breaker + idempotency +
  the persisted lifecycle. Reusing `DeliveryService` gives all three with **no** duplicated resilience
  logic; the report rests at `sent` (direct SMTP has no delivery webhook/poll — matching "generated and
  dispatched, not delivered").
- **Open/Closed (Principle II), correctly scoped** — adding the report *channel* is one new adapter + a
  bootstrap binding, with **no edits to existing channel adapters**. Adding **attachment** support to
  `Payload`/`DeliveryService` is a deliberate **one-time capability extension** of the shared flow (any
  future channel benefits) — not the per-channel edit Open/Closed forbids (per the user's clarification).
- **No histogram recursion without bookkeeping** — making the report dispatch **server-owned**
  (`user_id NULL`) means the aggregation's `user_id` grouping (plus a `user_id IS NOT NULL` filter)
  excludes reports automatically; send-history (filtered by owner) hides them too. No marker column, no
  per-row exclusion logic.
- **Sync, thread-safe** — the worker pipeline is synchronous on the `io`/threads pool; psycopg v3 and
  `smtplib` are thread-safe. A sync SMTP adapter matches that execution model exactly — the shape a real
  `EmailChannel` would take. The async `aiosmtplib` `Mailer` stays the API-path auth-email adapter,
  untouched.
- **No adapter-level failure injection** — resilience is proven by **injecting a failing report
  `ChannelPort`** into `DeliveryService` in-process (exactly like the existing channel-resilience tests),
  not by routing real mail through `provider_sim`.

**Alternatives considered**:
- *Reuse `SimulatedEmailChannel`* — rejected: it is HTTP→`provider_sim` with no attachment support;
  reusing it would force edits to an existing adapter and entangle reports with the webhook-confirmation
  flow. A new channel adapter is cleaner.
- *Ephemeral, task-level-only resilience (the earlier draft)* — rejected by the user: reports should be
  persisted snapshots with the full resilience model, like any other send.
- *A separate `ReportDeliveryService` paralleling `DeliveryService`* — rejected: duplicates the resilience
  orchestration; reusing the existing pipeline (with a one-time attachment capability) is DRY and is what
  the attachment feature legitimately calls for.
- *Attribute report sends to an admin instead of the server* — rejected: it would inflate the admin's
  personal + the global histogram by ~1,001/cycle, distorting the very stats being reported.

---

## 2. Admin provisioning — idempotent Alembic data migration reading env (placeholder refused outside dev)

**Decision**: Provision the single admin in an **idempotent Alembic data migration** (`0003`) that reads
`settings.admin_email` / `settings.admin_password`, argon2-hashes the password, and inserts the
pre-verified `is_admin=true` row `ON CONFLICT (lower(email)) DO NOTHING`. Credentials default to a
**dev-only placeholder** (`admin@localhost` / `admin`); a `settings` validator **rejects the placeholder
password when `environment != "dev"`**, exactly mirroring the existing `_PLACEHOLDER_JWT_SECRET` pattern.

**Rationale**:
- Honors the user's GitLab-style intent (a known default in dev; "your responsibility to set real
  credentials" in prod) **without** violating **FR-002** / **Principle VI** ("credentials … never
  hard-coded or committed"): the committed value is a *dev-only placeholder*, not a secret, and the real
  prod secret arrives via env. The codebase already blesses this exact pattern for the JWT secret.
- A **data migration** is the spec's first-listed option (FR-001) and runs through the existing one-shot
  **migrate Job** (constitution VII — never from the API start command), so no new provisioning component
  is needed and re-provisioning is naturally idempotent (Alembic runs once per DB; `ON CONFLICT DO
  NOTHING` guards re-seed on a shared DB).
- **Fail-fast in prod**: if the operator forgets to set `ADMIN_PASSWORD`, the settings validator refuses
  the placeholder and the migrate Job fails loudly — surfacing the misconfiguration before the app serves.

**Alternatives considered**:
- *Static `admin`/`admin` literally in the migration file* — rejected: a committed credential (FR-002 /
  VI violation). The placeholder-in-settings indirection fixes this while keeping the same UX.
- *Separate bootstrap CLI / one-shot Job* (the planner's first proposal) — viable, but a second
  provisioning component when the migrate Job already exists; the migration approach the user preferred is
  cleaner here.

**Note on coupling**: the data migration imports the project's argon2 hasher + settings. This couples one
historical migration to app code; acceptable because it runs once and argon2 defaults are stable. The
`is_admin` **DDL** and the data seed live in the same revision (add column → create config table → seed
config singleton → seed admin).

---

## 3. Hour-bucket timestamp — derived from the existing `sent` transition (no denormalization)

**Decision**: Bucket each qualifying send by `EXTRACT(HOUR FROM dt.at AT TIME ZONE 'UTC')` where `dt` is
the `delivery_transition` row with `to_status='sent'`. **No** new `delivery.sent_at` column.

**Rationale**:
- "Reached at least `sent`" is exactly "a `delivery_transition` with `to_status='sent'` exists" — written
  once by `SyncDeliveryRepository.record_sent`. This is the append-only single source of truth (Principle
  IV); deriving from it avoids a redundant denormalized column and keeps the model honest (per user: "use
  already available data, do not duplicate").
- Pre-send validation failures go `queued→failed` directly (no `sent` transition) and are excluded for
  free; a later `sent→delivered|failed` confirmation does not remove the `sent` transition, so anything
  that *ever reached* `sent` still counts (matches the clarification).
- `AT TIME ZONE 'UTC'` makes the hour-of-day independent of the DB session timezone (timezone-independence
  edge case).

**Seeding consequence**: the seeder must insert a `sent` `delivery_transition` per qualifying delivery
with an **explicit `at`** (the column's `server_default now()` is overridden) spread across all 24 hours
and many dates. See §6.

**Alternatives considered**:
- *Add `delivery.sent_at`* — rejected (chosen against by the user): faster single-table `GROUP BY` and
  trivial seeding, but a denormalized duplicate of transition truth; the join is cheap enough at 500K.

---

## 4. Scheduling — Celery Beat tick + DB-anchored due-check

**Decision**: Introduce a **Celery Beat** process (new `beat` Deployment, **replicas = 1**) with a single
**static** schedule entry that fires `stats_report_tick` every `stats_report_due_check_interval_s`
(default **60 s**). The tick reads `stats_report_config` and, when `interval_seconds ≠ 0` and
`now ≥ anchor_at + interval_seconds`, runs the cycle on the `cpu` pool and sets `anchor_at` to the fire
time. A frequency `POST` sets `anchor_at = now()`.

**Rationale**:
- The cadence is an arbitrary interval (≥ 24 h, runtime-changeable) — it **cannot** be a static crontab.
  Keeping cadence in the DB and letting a frequent fixed tick check due-ness is the standard pattern; it
  needs **no dynamic-beat dependency** (no `django-celery-beat`/RedBeat) because the Beat schedule itself
  is the one static 60 s tick.
- **Survives restarts** and makes the spec's rules fall out naturally: "changing frequency resets the
  schedule" = `anchor_at = now()` on POST → next fire is one full interval later; "disabled" =
  `interval_seconds = 0` → the tick never fires a cycle; "in-flight cycle completes under prior settings"
  = the cycle already running is unaffected, the new anchor governs only the next decision.
- **`replicas = 1`** for `beat`: Beat is a singleton scheduler; two replicas would double-fire. (The
  `cpu`/`io` *workers* still scale independently.) A 60 s tick granularity means a report fires within
  ≤ 60 s of becoming due — negligible against a ≥ 24 h cadence.

**Alternatives considered**:
- *Dynamic DB-backed beat scheduler (RedBeat / celery-sqlalchemy-scheduler)* — rejected: overkill; we have
  exactly one logical schedule and already store cadence ourselves.
- *APScheduler / a custom asyncio timer in the API* — rejected: scheduling belongs off the API process
  (which is single-process uvicorn scaled by replica count — a timer there would multi-fire); Celery Beat
  is the constitution-aligned mechanism.

---

## 5. Graphing — matplotlib (Agg) → attached PNG, rendered on the prefork pool

**Decision**: Render each report with **matplotlib** using the headless **Agg** backend — a 24-bar bar
chart (x = UTC hour 00–23, y = qualifying-send count) saved to PNG bytes — behind a `GraphRenderer` port.
The PNG is **attached** to the email. Rendering runs on the **prefork `cpu`** pool.

**Rationale**:
- matplotlib is the well-regarded community default for static charts (user prefers libraries over
  hand-rolling); the **Agg** backend needs no display/GUI and runs cleanly in a worker process
  (`matplotlib.use("Agg")` before `pyplot` import). It is the only new runtime dependency.
- Behind a `GraphRenderer` port, matplotlib is an isolated, swappable adapter and the renderer is
  unit-testable (assert a non-empty, valid PNG) without coupling `application/` to the library.
- Rendering **~1,001 PNGs per cycle is genuinely CPU-bound** — the right kind of work for the prefork pool
  the constitution reserves for exactly this "usage bar-graph" task.

**Alternatives considered**:
- *Plotly* — rejected: oriented to interactive HTML/JS; static image export pulls in `kaleido`/a browser
  engine — heavier for a simple attached PNG.
- *Pillow hand-rolled bars* — rejected: re-implements axes/labels/scaling a charting lib gives for free
  (against the user's library preference).
- *Inline-CID embed vs attach* — chose **attach** (simplest, renders in Mailpit and ordinary clients);
  embedding is a trivial future change if desired.

---

## 6. Cycle execution split — aggregate + render + persist on `cpu`, deliver on `io`

**Decision**: `stats_report_tick` (on the **`cpu`** queue) does the whole compute step: one SQL
aggregation pass returns per-user-per-hour counts **and** the global per-hour counts (plus the account
list with emails + `is_admin`); the worker buckets into 24-slot histograms, **renders all PNGs** (personal
per account, + global for the admin), and **persists each as a server-owned `dispatch` + queued
`delivery`** (`user_id NULL`, `channel='report'`, `attachment_png`=PNG); then it **enqueues the existing
`app.tasks.sending.deliver` task per delivery on the `io` queue**. The io `deliver` task runs
`DeliveryService.deliver_one` unchanged — breaker + idempotency + lifecycle — reading the PNG off the
dispatch and handing it to the report channel.

**Rationale**:
- Keeps **CPU work (aggregate + render) on prefork** and **I/O (SMTP) on threads** — the constitution's
  mixed-workload split, finally exercised end-to-end — and **reuses the existing `deliver` task** rather
  than adding a parallel one.
- One SQL `GROUP BY (user_id, hour)` over `delivery_transition⋈delivery⋈dispatch` (filter
  `to_status='sent' AND user_id IS NOT NULL`) yields the whole grid in a single pass; the global row is the
  same data summed (admin's own sends included — no double count). Accounts with **zero** qualifying sends
  are absent from the grid and get an **all-zero** histogram by left-joining the full account list.
- **Per-recipient isolation**: each report is its own `delivery` + `deliver` task, so one recipient's
  repeated failure (after retries) is logged/telemetry-surfaced, persisted as `queued→failed`, and never
  aborts the others (FR-019, SC-003).

**Idempotency (reused)**: each report is its own `delivery` row, so the existing per-`delivery_id`
idempotency claim is exactly a (cycle, account, scope) key — a `deliver` retry never double-sends. The
cycle runs once per due-period (`claim_if_due` advances the anchor atomically), so it never creates
duplicate report rows.

**Broker-payload note**: because the PNG is stored on the `dispatch` row, the `deliver` message carries
only the `delivery_id` (tiny) — avoiding the ~20 MB/cycle of base64 PNGs an in-message design would push
through RabbitMQ. The ~1,001 small PNGs live in Postgres for the cycle; fine at portfolio scale.

---

## 7. Admin authorization — `current_admin` dependency over the existing token flow

**Decision**: Reuse 003's OAuth2/PyJWT auth. Add an `api/deps.py` `current_admin` dependency that resolves
`current_user` (→ **401** on missing/invalid/expired token, unchanged) then loads the account and requires
`is_admin` (→ **403** for an authenticated non-admin). The admin frequency router depends on
`current_admin`; nothing else changes about ordinary endpoints, so the admin keeps every ordinary
capability and gains no cross-user access (FR-004).

**Rationale**: Smallest correct surface — the 401-vs-403 split (FR-005) is the only new authz rule, and it
composes on top of the existing `current_user`. Endpoint mounted at `/api/v1/admin/stats-report/frequency`
(the spec's `/admin/...` under the codebase's established `/api/v1` prefix).

---

## 8. Settings additions

| Setting | Default | Notes |
|---|---|---|
| `admin_email` | `admin@localhost` | dev placeholder; real value via env in prod |
| `admin_password` | `admin` (`_PLACEHOLDER_ADMIN_PASSWORD`) | **refused outside dev** by validator (mirrors JWT) |
| `report_mail_from` | falls back to `mail_from` | From-address for report emails |
| `stats_report_due_check_interval_s` | `60` | Beat tick cadence (due-check granularity) |
| _(no new retry knobs)_ | — | report sends reuse the existing `retry_*` / `breaker_*` resilience knobs via `DeliveryService` |

Report SMTP reuses the existing `smtp_host` / `smtp_port` (dev → Mailpit). No `os.environ` reads — all via
`pydantic-settings`.

---

## 9. Testing seams (Principle V)

- **Real Postgres + RabbitMQ** (Testcontainers) for all integration tests.
- **Report cycle round-trip**: drive a **real `cpu` worker** (the tick/cycle) and **real `io` worker** (the
  `deliver` sends); point the report channel's SMTP at a **local `aiosmtpd` sink** reachable by the worker
  subprocess (an in-process mock can't patch a worker subprocess — the seam 003 documented; real external
  SMTP is never hit). Assert the captured recipients/subjects, that a valid PNG was attached, **and** that
  each report persisted a **server-owned** `dispatch`/`delivery` (`user_id NULL`) absent from `GET /sends`.
  Worker rows isolated by **truncation**.
- **Resilience** (`test_report_resilience.py`): exercise `DeliveryService` on a report delivery
  **in-process** with an **injected failing report `ChannelPort`** to prove retry/backoff → breaker, a
  persisted `queued→failed`, per-recipient isolation, and that the remaining recipients are still
  dispatched.
- **Aggregation correctness**: seed a known small dataset → run the cycle → assert each scope's 24 buckets
  exactly equal the seeded counts, bars sum to the scope total, zero-send user → all-zero, never-`sent` →
  excluded, and a second cycle (which itself created report rows) leaves totals unchanged (no recursion —
  server-owned reports are filtered out).
- **Renderer unit test**: `MatplotlibGraphRenderer.render_hour_histogram([...24...], title)` returns
  non-empty PNG bytes with the PNG magic header.
- **Seed test**: run `seed.py` at reduced N → assert account/send counts and 24-hour/multi-date spread.

---

## 10. Operations (constitution VII)

- New **`beat` Deployment** (`deploy/k8s/base/beat.yaml`, **replicas = 1**) — same multi-stage pinned
  image, command `celery -A app.tasks.celery_app beat --loglevel=info`. Added to base `kustomization.yaml`.
- The **`cpu` worker** Deployment already exists (prefork, `-Q cpu`) — now actually processes the tick +
  cycle. The **`io` worker** already handles the report emails' queue.
- Admin credentials supplied via the existing k8s **secret** (`secret.env` in dev; required in prod). The
  settings validator refusing the placeholder outside dev makes a missing prod secret a hard, early
  failure.
- Report SMTP in dev → existing **Mailpit** (reuse `smtp_host`/`smtp_port`); the rendered graph is
  viewable in the Mailpit UI for manual validation.
- Schema + admin seed ship as Alembic **`0003`**, applied by the existing migrate Job (no API-start
  migration; no out-of-band DDL).
