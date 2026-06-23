---
description: "Task list for 004-admin-stats-report"
---

# Tasks: Admin Account & Server-Wide Stats-Report

**Input**: Design documents from `specs/004-admin-stats-report/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (all present)

**Tests**: Testing is **NON-NEGOTIABLE** (constitution Principle V) and this feature touches the API,
persistence, and channel sends — so unit + integration test tasks are included per story (real
Postgres + RabbitMQ via Testcontainers; the report channel's SMTP is captured by a local **`aiosmtpd`**
sink reachable by the worker subprocess; resilience is proven by injecting a **failing report
`ChannelPort`** into `DeliveryService`; no real external SMTP in the suite).

**Organization**: Tasks are grouped by user story (US1, US2, US3) so each story is independently
implementable and testable. Backend-only feature (`frontend/` untouched).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 / US2 / US3 (omitted for Setup, Foundational, Polish)
- All paths are repo-relative; backend code lives under `backend/`.

## Design recap (read before implementing — C1 resolved with the user)

Report emails are **real, persisted sends** that reuse the **existing resilient delivery pipeline**
(`DeliveryService`: retry/backoff + per-destination circuit breaker + idempotency + the persisted
`queued → sent → delivered | failed` lifecycle). They are delivered by a **new `Channel.REPORT`
`ChannelPort` adapter** (real `smtplib`) that attaches the rendered PNG; the shared `Payload` gains a
**one-time, additive attachment capability** (existing channel adapters ignore it — SC-010). Each report
is a **server-owned** `dispatch` (`user_id = NULL`, `channel = 'report'`, `attachment_png` = the PNG) with
one `delivery` (`destination` = the account's email). Because they are server-owned, the aggregation
(filtered `user_id IS NOT NULL`) and every user's send-history (filtered by owner) **exclude** them — no
recursion, no marker bookkeeping. A report **rests at `sent`** (direct SMTP returns no delivery receipt).

## Key test seam (read before US1/US2 tests)

The test `migrated_db` fixture builds schema with `Base.metadata.create_all` — it does **not** run the
`0003` Alembic **data seed**. Consequences: (a) the admin account is seeded via a **factory**
(`make_admin`), not relied on from the migration in most tests; (b) the `stats_report_config` singleton is
**self-created** by `StatsConfigRepository.get()` on first read; (c) the migration's admin-seed +
idempotency is validated by a **dedicated Alembic-upgrade test** (T012). The report cycle is driven by a
**real `cpu` + `io` worker**; the io `deliver` task sends via the report channel to a local `aiosmtpd`
sink (the in-process-mock-can't-patch-a-subprocess seam 003 documented).

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 [P] Add `matplotlib` as a **pinned** runtime dependency and `aiosmtpd` as a **pinned dev/test**
      dependency in `backend/pyproject.toml`; refresh `backend/uv.lock` via `uv sync`; confirm the headless
      backend imports (`python -c "import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot"`).
- [X] T002 [P] Extend `backend/app/settings.py`: `admin_email` (default `admin@localhost`), `admin_password`
      (default `_PLACEHOLDER_ADMIN_PASSWORD = "admin"`), `report_mail_from: str | None = None`,
      `stats_report_due_check_interval_s: float = 60.0`; add a `model_validator(mode="after")`
      `_require_real_admin_password_outside_dev` that refuses the placeholder when `environment != "dev"`,
      **mirroring** `_require_real_jwt_secret_outside_dev`. (Report sends reuse the existing `retry_*` /
      `breaker_*` knobs — **no** new retry settings.)

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: No user-story work can begin until this phase is complete.

- [X] T003 [P] Add `is_admin: bool = False` to the frozen `UserAccount` dataclass in
      `backend/app/domain/accounts.py` (pure domain).
- [X] T004 [P] Create `backend/app/domain/stats.py` (pure): constants `DISABLED = 0`,
      `MIN_INTERVAL_SECONDS = 86_400`, `DEFAULT_INTERVAL_SECONDS = 2_592_000`;
      `StatsReportConfig(interval_seconds, anchor_at)` with `is_enabled`, `next_run_at() -> datetime | None`,
      `is_due(now)`, `validate_interval(seconds)` (raise domain `ValidationError` for `1..86_399`),
      `with_interval(seconds, now)` (validate + reset `anchor_at=now`); `HourHistogram(counts: tuple[int,...])`
      with `from_hour_counts(Mapping[int,int])` (24 buckets, missing → 0) and `total`; and `ReportScope`
      (personal | global → title/label).
- [X] T005 [P] In `backend/app/adapters/persistence/models.py`: add `is_admin` to `UserAccount`
      (`Boolean`, `server_default text("false")`, `nullable=False`); add the `StatsReportConfig` singleton
      model (`id` PK `CheckConstraint("id = 1")`, `interval_seconds` default 2592000 with
      `CheckConstraint("interval_seconds = 0 OR interval_seconds >= 86400")`, `anchor_at`, `updated_at`);
      and apply the **dispatch deltas** — make `Dispatch.user_id` **nullable**, add `attachment_png`
      (`LargeBinary`, nullable), and widen `ck_dispatch_channel` to `IN ('email','sms','push','report')`.
- [X] T006 Extend `backend/app/ports/repositories.py` with the `StatsConfigRepository` Protocol
      (`get() -> StatsReportConfig` self-creating the singleton; `set_interval(seconds, anchor_at)`;
      `advance_anchor(anchor_at)`) — one shape; async + sync impls land later (T014 / T035).
- [X] T007 Create Alembic migration `backend/migrations/versions/0003_admin_and_stats.py`
      (`revision="0003"`, `down_revision="0002"`): `upgrade()` adds `is_admin` (NOT NULL server_default
      false), creates `stats_report_config` (+ both CHECKs) and **seeds the singleton** `(1, 2592000,
      now(), now())`; **alters `dispatch`** — `ALTER COLUMN user_id DROP NOT NULL`, add `attachment_png`
      (`bytea`, nullable), drop+recreate `ck_dispatch_channel` to include `'report'`; **seeds the admin** —
      `INSERT ... (lower(:admin_email), :argon2_hash, true, true) ON CONFLICT (lower(email)) DO NOTHING`
      using `settings.admin_email` + the project argon2 hasher over `settings.admin_password`. `downgrade()`
      reverses each.

**Checkpoint**: Schema + domain + ports ready — US1, US2, US3 can proceed.

---

## Phase 3: User Story 1 — Admin account & frequency control (Priority: P1) 🎯 MVP

**Goal**: A seeded, pre-verified admin can read/set the single server-wide stats-report frequency;
non-admins are forbidden, unauthenticated callers are unauthenticated, and the admin gains no
cross-user access.

**Independent Test**: Sign in as the seeded admin; GET default `{interval_seconds:2592000, enabled:true}`;
POST `86400` persists; POST `3600` → 422 + unchanged; POST `0` → `enabled:false`; non-admin → 403; no
token → 401.

### Tests for User Story 1

- [X] T008 [US1] Test support: add `is_admin` param to `make_user` and a `make_admin(...)` helper in
      `backend/tests/factories/__init__.py`; add an `admin_client` fixture (seed admin via factory with a
      known password hash, then log in) in `backend/tests/conftest.py`.
- [X] T009 [P] [US1] Unit test `backend/tests/unit/test_stats_config.py`: `validate_interval`
      (0 ok, ≥86400 ok, `1..86399` raises), `with_interval` resets `anchor_at`, `is_enabled`,
      `next_run_at`/`is_due` (disabled → `None`, never due).
- [X] T010 [P] [US1] Unit test `backend/tests/unit/test_settings_validators.py`: the admin-password
      placeholder is accepted in `dev` and **refused** when `environment != "dev"` (mirror the JWT test).
- [X] T011 [P] [US1] Integration test `backend/tests/integration/test_admin_frequency.py` (uses
      `admin_client`): GET default; POST 86400 persists; POST 3600 → **422**, stored value unchanged;
      POST 0 → disabled; authenticated non-admin → **403** on GET and POST; no/invalid token → **401**.
- [X] T012 [P] [US1] Integration test `backend/tests/integration/test_admin_seed_migration.py` **(G1)**:
      against a dedicated clean Postgres, run `alembic upgrade head` with known `ADMIN_EMAIL`/`ADMIN_PASSWORD`;
      assert exactly one `is_admin`/`is_verified` admin row whose argon2 hash verifies the password; run the
      upgrade/seed again → still exactly one (ON CONFLICT idempotency, FR-001).
- [X] T013 [P] [US1] Integration test `backend/tests/integration/test_admin_no_cross_user.py` **(G2)**:
      with the admin token and a second ordinary user's resources (contacts/templates/sends via factories),
      assert the admin is denied (403/404) exactly like any non-owner — no cross-user access (FR-004).

### Implementation for User Story 1

- [X] T014 [US1] Implement `AsyncStatsConfigRepository` in
      `backend/app/adapters/persistence/async_repo.py` (asyncpg): `get` self-creates the `id=1` row,
      `set_interval` UPDATEs `WHERE id=1`, `advance_anchor` UPDATEs `anchor_at`.
- [X] T015 [US1] In the same `async_repo.py`, extend `AsyncAccountRepository` with an `is_admin` read
      (e.g. `get_admin_flag(user_id) -> bool`) for `current_admin`. (Sequential after T014 — same file.)
- [X] T016 [US1] Implement `StatsConfigService` (async) in `backend/app/application/stats_config.py`:
      `get_frequency() -> FrequencyView(interval_seconds, enabled)` and `set_frequency(interval_seconds)`
      (validate via domain → 422 on `1..86399`; persist; reset `anchor_at = clock.now()`; `0` disables).
- [X] T017 [P] [US1] Add `FrequencyResponse` (`interval_seconds`, `enabled`) and `FrequencyUpdate`
      schemas in `backend/app/api/schemas.py`.
- [X] T018 [P] [US1] Add the `current_admin` dependency in `backend/app/api/deps.py`: resolve
      `current_user` (401 unchanged), load the admin flag, raise **403** `"admin privileges required"`.
- [X] T019 [US1] Implement the admin router in `backend/app/api/routers/admin.py`:
      `GET`/`POST /api/v1/admin/stats-report/frequency` depending on `current_admin`; map domain
      `ValidationError` → HTTP 422 with the message from `contracts/admin-stats-api.yaml`.
- [X] T020 [US1] Wire it up: build the async `StatsConfigRepository` + `StatsConfigService` (and the
      admin-flag lookup) into the `Container` in `backend/app/bootstrap.py`; register the admin router in
      `backend/app/main.py`.
- [X] T021 [US1] Add `ADMIN_EMAIL`/`ADMIN_PASSWORD` to `deploy/k8s/overlays/dev/secret.env` (dev
      placeholder) and `secret.env.example`, and document them as **required** for `overlays/prod/`.

**Checkpoint**: US1 fully functional and independently testable — the MVP.

---

## Phase 4: User Story 2 — Scheduled per-hour reports by email (Priority: P1)

**Goal**: On the configured cadence, a Celery Beat tick runs the CPU-bound aggregation + 24-bar render on
the `cpu` pool, **persists a server-owned report send per recipient**, and enqueues the **existing**
resilient `deliver` task on the `io` pool (breaker + idempotency + lifecycle) via a new `Channel.REPORT`
SMTP adapter; the admin additionally gets a global graph.

**Independent Test**: Seed an admin + a few users with known `sent` deliveries across UTC hours; drive one
cycle with real `cpu`+`io` workers; assert each account's 24 buckets match its data, a zero-send user gets
an all-zero graph, the admin gets **exactly two** reports, global = per-user sums (admin included),
never-`sent` counts zero, a second cycle leaves totals unchanged, and each report persisted a
**server-owned** `dispatch`/`delivery` (lifecycle to `sent`) that does **not** appear in `GET /sends`.

### US2 enabling contracts (shared additions)

- [X] T022 [P] [US2] Add `Channel.REPORT = "report"` to `backend/app/domain/channels.py`.
- [X] T023 [P] [US2] Extend the shared `Payload` in `backend/app/ports/channels.py` with optional
      `attachment: bytes | None = None` and `attachment_name: str = "report.png"` (additive — existing
      adapters ignore them).
- [X] T024 [P] [US2] In `backend/app/domain/dispatch.py`: make `Dispatch.user_id: UUID | None` and add
      `attachment: bytes | None = None` (pure domain; mirrors the persisted server-owned report shape).
- [X] T025 [P] [US2] Add the `GraphRenderer` Protocol in `backend/app/ports/graph.py`
      (`render_hour_histogram(counts: Sequence[int], *, title: str) -> bytes`, length-24 → PNG).
- [X] T026 [P] [US2] Extend `backend/app/ports/repositories.py` with `AccountRef` (`id, email, is_admin`),
      `SyncReportAggregationRepository` (`per_user_hour_counts`, `global_hour_counts`, `list_accounts`), and
      `SyncReportSendRepository` (`create_report_delivery(*, to_email, subject, body, png) -> UUID`).

### Tests for User Story 2

- [X] T027 [US2] Test support: add a `make_sent_delivery(...)` factory (dispatch + delivery `status='sent'`
      + a `delivery_transition` `to_status='sent'` with an **explicit `at`**) in
      `backend/tests/factories/__init__.py`; add a **`aiosmtpd` SMTP sink** fixture (in-process controller
      on a free port, reachable by the worker subprocess via `SMTP_HOST`/`SMTP_PORT`) and a **failing
      report `ChannelPort`** fake in `backend/tests/fakes.py`; add a `cpu`+`io` worker + **tick-trigger**
      fixture (invoke `stats_report_tick` directly after nudging the anchor) in
      `backend/tests/conftest.py`; rows cleaned by truncation.
- [X] T028 [P] [US2] Unit test `backend/tests/unit/test_hour_histogram.py`: `from_hour_counts` fills 24
      buckets (missing → 0), `total` sums, empty → all-zeros.
- [X] T029 [P] [US2] Unit test `backend/tests/unit/test_graph_renderer.py`:
      `MatplotlibGraphRenderer.render_hour_histogram([...24...], title=...)` returns non-empty PNG bytes
      (magic header); rejects non-length-24 input.
- [X] T030 [P] [US2] Integration test `backend/tests/integration/test_report_cycle.py` (real `cpu`+`io`
      workers, `aiosmtpd` sink): per-scope 24-bucket correctness vs seeded data, zero-send user → all-zero,
      admin → exactly two reports (personal + global), global = sum across users (admin included, no
      double-count), never-`sent` excluded, a second cycle leaves histograms identical (no recursion,
      SC-009), and each report persisted a **server-owned** `dispatch`/`delivery` (`user_id NULL`,
      `channel='report'`, lifecycle → `sent`) that is **absent from `GET /api/v1/sends`** (FR-019).
- [X] T031 [P] [US2] Resilience test `backend/tests/integration/test_report_resilience.py`: run
      `DeliveryService.deliver_one` on a report delivery **in-process** with an injected **failing report
      `ChannelPort`**; assert retry/backoff → breaker, a persisted `queued → failed`, per-recipient
      isolation, and that the remaining recipients are still delivered (FR-019, SC-003).

### Implementation for User Story 2

- [X] T032 [US2] In `backend/app/application/delivery.py`, thread the attachment through the shared flow:
      `Payload(title=dispatch.title, content=dispatch.content, attachment=dispatch.attachment)` (one-time
      additive change; existing channels unaffected — `attachment` defaults `None`).
- [X] T033 [P] [US2] Implement `MatplotlibGraphRenderer` in
      `backend/app/adapters/graphing/matplotlib_renderer.py` (+ package `__init__.py`): `matplotlib.use("Agg")`
      **before** importing `pyplot`; 24 bars (x `00..23`, y = count, scope title); return `BytesIO.getvalue()`.
- [X] T034 [P] [US2] Implement `SmtpReportEmailChannel` (ChannelPort, `channel = Channel.REPORT`) in
      `backend/app/adapters/channels/report_email/__init__.py`: stdlib `smtplib`, multipart `EmailMessage`,
      attach `payload.attachment` as `payload.attachment_name`, `From = settings.report_mail_from or
      settings.mail_from`, host/port = `settings.smtp_host`/`smtp_port`; `validate` checks email format;
      raise `TransientChannelError`/`PermanentChannelError` on SMTP failure; `confirmation_mode = WEBHOOK`
      (no webhook arrives → rests at `sent`). **Do not edit** existing channel adapters.
- [X] T035 [US2] In `backend/app/adapters/persistence/sync_repo.py` (psycopg): implement
      `SyncStatsConfigRepository` (mirrors T014), `SyncReportAggregationRepository` (the data-model §3.1
      query filtered `to_status='sent' AND d.user_id IS NOT NULL`, plus global `GROUP BY hour` and
      `list_accounts`), and `SyncReportSendRepository.create_report_delivery` (INSERT server-owned dispatch
      `user_id NULL`/`channel='report'`/`attachment_png` + queued delivery `destination=to_email`/
      `contact_id NULL` + initial queued transition; return `delivery_id`). Ensure `SyncDispatchReader.get`
      maps `attachment_png` → `Dispatch.attachment`.
- [X] T036 [US2] Implement `ReportCycleService` + `ReportDueService` in
      `backend/app/application/reporting.py` (framework-free, sync): `run_cycle()` loads grids + account
      list (one pass), renders each account's personal PNG → `create_report_delivery` → `enqueue_deliver`,
      and for the admin renders the **global** PNG → a second delivery; returns counts; `claim_if_due(now)`
      sets `anchor_at = now()` (the claim time) iff `config.is_due(now)`. **Instrument with structlog binds
      + OTel spans** on the cycle/due-check (G4).
- [X] T037 [US2] Implement `stats_report_tick` (name `app.tasks.reporting.stats_report_tick`, `cpu`/prefork)
      in `backend/app/tasks/reporting.py`: if `ReportDueService.claim_if_due(now)` run
      `ReportCycleService.run_cycle()` enqueuing the **existing** `app.tasks.sending.deliver(delivery_id,
      'report')` on `io` per recipient; no-op when disabled/not due. **OTel span on the tick** (G4). (No new
      `send_report_email` task — report delivery reuses `deliver`.)
- [X] T038 [US2] Extend `WorkerContainer` in `backend/app/tasks/deps.py` (stats config repo, aggregation
      repo, report-send repo, `GraphRenderer`, `ReportCycleService`/`ReportDueService`, `enqueue_deliver`
      callback); and bind `Channel.REPORT → SmtpReportEmailChannel` in `build_channel_registry`
      (`backend/app/bootstrap.py`) so `deliver_one` resolves the report channel.
- [X] T039 [US2] In `backend/app/tasks/celery_app.py` add `"app.tasks.reporting"` to `include` and set
      `app.conf.beat_schedule` `stats-report-due-check` → `stats_report_tick`,
      `schedule = settings.stats_report_due_check_interval_s`, `options={"queue": "cpu"}`.
- [X] T040 [US2] Add `deploy/k8s/base/beat.yaml` (Deployment, **replicas: 1**, same `__API_IMAGE__`,
      command `celery -A app.tasks.celery_app beat --loglevel=INFO`) and add it to
      `deploy/k8s/base/kustomization.yaml`; ensure `report_mail_from` + SMTP env reach the `cpu`+`io`
      workers via the overlays (dev → Mailpit).

**Checkpoint**: US1 + US2 both work independently — the report cycle is demonstrable.

---

## Phase 5: User Story 3 — Seeded analytics dataset (Priority: P2)

**Goal**: A standalone seeder bulk-inserts ≈1,000 accounts and ≈500,000 completed **user-owned** sends
across all 24 UTC hours and many dates, bypassing the live pipeline, to exercise the aggregation at scale.

**Independent Test**: Run the seeder at reduced N; assert ~N accounts and ~M `sent` transitions exist,
spread across all 24 hours and multiple dates; then run the aggregation and confirm per-hour totals match.

### Tests for User Story 3

- [ ] T041 [P] [US3] Integration test `backend/tests/integration/test_seed.py`: run `seed.py` at reduced N
      (e.g. 20 accounts / 2,000 sends); assert account + `sent`-transition counts, all 24 UTC hours and ≥2
      dates appear, and the §3.1 aggregation (`SyncReportAggregationRepository`, `user_id IS NOT NULL`)
      per-hour totals exactly match the generated counts (SC-005/SC-007).

### Implementation for User Story 3

- [ ] T042 [US3] Create `backend/scripts/seed.py` — standalone **COPY-based** bulk insert (sync engine):
      ~1,000 `user_account` rows (synthetic emails, fixed hash, `is_verified=true`, `is_admin=false`) and
      ~500,000 **user-owned** completed sends (one `dispatch` with a real `user_id` + one `delivery`
      (`status` in `sent`/`delivered`) + one `delivery_transition` `to_status='sent'` with an **explicit
      `at`** spread across all 24 UTC hours and a range of dates). Argparse `--accounts`/`--sends`; runnable
      as `uv run python backend/scripts/seed.py --accounts 1000 --sends 500000`; no idempotency/breaker/fan-out.

**Checkpoint**: All three stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T043 [P] Update docs: note the new `beat` workload, the now-active `cpu` worker, the report
      `Channel.REPORT` + attachment capability, the seeder, and admin credentials in the README / overview.
- [ ] T044 Run `uv run ruff check --fix . && uv run ruff format .` and `uv run mypy .` (strict) across all
      new/edited modules until clean.
- [ ] T045 Run `uv run pytest` (full suite) on the host, then execute the `quickstart.md` manual smoke on
      kind (admin login, frequency endpoints, seed, nudge anchor, inspect Mailpit graphs, verify
      server-owned report rows are absent from `GET /sends`).
- [ ] T046 [P] Confirm CI gates (ruff, mypy, pytest, coverage → Coveralls) are green for the branch.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)** → no deps.
- **Foundational (P2)** → depends on Setup; **blocks all stories**. The `0003` migration (T007) and ORM
  (T005) carry the dispatch deltas US2 needs, but they don't affect US1/US3 behaviour.
- **US1 (P3)**, **US2 (P4)**, **US3 (P5)** → each depends only on Foundational; independently testable.
  US3's full test (T041) reuses US2's aggregation repo; its seeder (T042) is independent.
- **Polish (P6)** → after the desired stories are complete.

### Within each story

- Test-support (factories/fixtures/fakes) → tests (written to fail) → implementation.
- US2 enabling contracts (T022–T026: enum, `Payload`, `Dispatch`, ports) come first so tests and impl can
  reference them.
- Same-file tasks are sequential: T014→T015 (`async_repo.py`); T006→T026 (`ports/repositories.py`).

### Critical path (US2)

- T035 (sync aggregation/report-send) ← T005 (ORM), T006/T026 (ports).
- T036 (cycle) ← T035 + T025 (renderer port) + T033 (renderer) + T024 (Dispatch).
- T037 (tick) ← T036 + T038 (worker container + report channel binding).
- T030/T031 (cycle/resilience tests) ← T032 (attachment passthrough) + T034 (report channel) on the green path.

---

## Parallel Opportunities

- **Setup**: T001, T002.
- **Foundational**: T003, T004, T005 in parallel; T006 after T004; T007 after T005 + T002.
- **US1 tests**: T009, T010, T011, T012, T013 in parallel (after T008).
- **US1 impl**: T017 (schemas) ∥ T018 (deps); T014→T015 sequential (same file).
- **US2 enablers**: T022, T023, T024, T025, T026 all in parallel (distinct files).
- **US2 adapters**: T033 (renderer) ∥ T034 (report channel).
- **US2 tests**: T028, T029, T030, T031 in parallel (after T027).
- Across stories: once Foundational is done, US1 / US2 / US3 can be staffed in parallel.

### Parallel example — US2 enabling contracts

```bash
Task: "Channel.REPORT in backend/app/domain/channels.py"                 # T022
Task: "Payload attachment in backend/app/ports/channels.py"              # T023
Task: "Dispatch user_id optional + attachment in backend/app/domain/dispatch.py"  # T024
Task: "GraphRenderer port in backend/app/ports/graph.py"                 # T025
Task: "aggregation + report-send repo protocols in ports/repositories.py" # T026
```

---

## Implementation Strategy

### MVP first (US1 only)

1. Phase 1 (Setup) → Phase 2 (Foundational) → Phase 3 (US1).
2. **STOP & VALIDATE**: `test_admin_frequency.py` + `test_admin_seed_migration.py` + `test_admin_no_cross_user.py`.
3. Demo: the admin identity + the single privileged config — the gate for the whole feature.

### Incremental delivery

1. Setup + Foundational → foundation ready.
2. US1 → test → demo (MVP).
3. US2 → test → demo (the report cycle; seed a small dataset via factories to exercise it).
4. US3 → test → demo (scale: ≈500K sends, aggregation correctness at volume).
5. Polish (ruff/mypy/coverage + quickstart smoke).

### Notes

- `[P]` = different files, no incomplete-task dependency.
- Tests are required (Principle V) — verify they fail before implementing.
- **SC-010**: the report email is **one new `ChannelPort` adapter** (`Channel.REPORT`) — do **not** edit
  existing channel adapters. Adding attachment support to `Payload`/`DeliveryService` is the deliberate,
  in-scope **capability extension** (channels can now carry attachments).
- Reports are **server-owned** (`dispatch.user_id NULL`) → excluded from aggregation (`user_id IS NOT NULL`)
  and from user send-history; they reuse the existing breaker + idempotency + persisted lifecycle and rest
  at `sent`.
- Workers use the **sync psycopg** engine (`sync_repo`), never asyncpg. CPU work (aggregate + render) →
  `cpu` pool; report email I/O → the existing `io` `deliver` task.
- Ship the `0003` migration in this PR; never edit an applied migration.
