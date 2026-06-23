# Data Model: Admin Account & Server-Wide Stats-Report

**Feature**: `004-admin-stats-report` | **Date**: 2026-06-22 | **Migration**: `0003_admin_and_stats`

This feature adds the `is_admin` column, a `stats_report_config` singleton table, and small **`dispatch`**
deltas (nullable `user_id`, an `attachment_png` column, a `'report'` channel), seeds **two rows** (the
config singleton and the admin account), and **reads/writes** the existing 003 notification tables
(aggregation reads; report sends are persisted as **server-owned** rows). Inherited tables (`user_account`,
`dispatch`, `delivery`, `delivery_transition`, …) are defined in 003's data model; only the deltas and the
read/write paths are here.

---

## 1. Schema changes (migration `0003`)

### 1.1 `user_account.is_admin` (new column)

| Column | Type | Constraints / Default | Notes |
|---|---|---|---|
| `is_admin` | `boolean` | `NOT NULL`, `server_default false` | Admin designation (FR-003). Set only by the seed; **no endpoint** grants/revokes it. |

- Backfill: existing rows default to `false`.
- No new index — admin is looked up by id (already PK) or by the seeded email (covered by the existing
  `lower(email)` unique index).

### 1.2 `stats_report_config` (new singleton table)

Holds the single, server-wide, persisted report cadence + scheduling anchor (FR-006/FR-007/FR-009/FR-010).

| Column | Type | Constraints / Default | Notes |
|---|---|---|---|
| `id` | `integer` | PK, `CHECK (id = 1)`, default `1` | **Singleton guard** — only one row can exist. |
| `interval_seconds` | `integer` | `NOT NULL`, default `2592000` (30 d) | `0` ⇒ reporting disabled; `≥ 86400` ⇒ enabled; `1–86399` never stored (rejected at the API). |
| `anchor_at` | `timestamptz` | `NOT NULL`, default `now()` | Scheduling anchor; `next_run = anchor_at + interval_seconds`. Reset to `now()` on every frequency change and advanced after each fired cycle. |
| `updated_at` | `timestamptz` | `NOT NULL`, `server_default now()`, `onupdate now()` | Audit. |

- **CHECK** `interval_seconds = 0 OR interval_seconds >= 86400` (defence-in-depth; the API validates
  first and returns the actionable error).
- Seeded with the single row `(1, 2592000, now(), now())` in the migration (FR-009: default 30 d,
  enabled).
- "Enabled" is **derived** (`interval_seconds <> 0`) — not a separate column.

### 1.3 Seeded admin row (data seed in `0003`)

Insert one `user_account` from settings (env), idempotently:

```sql
INSERT INTO user_account (id, email, password_hash, is_verified, is_admin)
VALUES (gen_random_uuid(), :admin_email_lower, :argon2_hash, true, true)
ON CONFLICT  -- on the lower(email) unique index
DO NOTHING;
```

- `email` = `settings.admin_email` (lowercased); `password_hash` = argon2 of `settings.admin_password`
  (the migration uses the project hasher). Both from env; the dev placeholder (`admin@localhost`/`admin`)
  is **refused outside dev** by the settings validator (FR-002).
- `is_verified=true` (pre-verified — no email-verification step, FR-002) and `is_admin=true`.
- `ON CONFLICT DO NOTHING` ⇒ re-provisioning never duplicates or overwrites the admin (FR-001, idempotent).

### 1.4 `dispatch` deltas (for server-originated report sends)

Reports reuse the 003 `dispatch`/`delivery`/`delivery_transition` tables; `0003` extends `dispatch`:

| Column / constraint | Change | Notes |
|---|---|---|
| `user_id` | **made nullable** | `NULL` ⇒ **server-originated** (no owning user). Excludes report sends from the histogram and from every user's send-history (both key off `user_id`). FR-020. |
| `attachment_png` | new `bytea`, nullable | The rendered 24-bar PNG, threaded into the channel `Payload` and attached by the report email channel. |
| `ck_dispatch_channel` | widened to `IN ('email','sms','push','report')` | Admits the new `Channel.REPORT`. |

- Existing user sends are unaffected (they always set `user_id` and never set `attachment_png`).
- `delivery.contact_id` is already nullable — report deliveries set it `NULL` (the recipient is the
  account's own email, not a contact). FR-017.

---

## 2. Domain entities (pure — `app/domain/stats.py`, `app/domain/accounts.py`)

These carry **no** SQLAlchemy/FastAPI/Celery/matplotlib imports (Principle II).

### 2.1 `UserAccount` (extend, `domain/accounts.py`)

Add `is_admin: bool` to the existing frozen dataclass:

```python
@dataclass(frozen=True, slots=True)
class UserAccount:
    id: UUID
    email: str
    is_verified: bool
    is_admin: bool = False
```

### 2.2 `StatsReportConfig` (new value object)

```python
DISABLED = 0
MIN_INTERVAL_SECONDS = 86_400        # 24 h
DEFAULT_INTERVAL_SECONDS = 2_592_000 # 30 d

@dataclass(frozen=True, slots=True)
class StatsReportConfig:
    interval_seconds: int
    anchor_at: datetime

    @property
    def is_enabled(self) -> bool: ...                 # interval_seconds != DISABLED
    def next_run_at(self) -> datetime | None: ...      # None if disabled, else anchor_at + interval
    def is_due(self, now: datetime) -> bool: ...       # enabled and now >= next_run_at
    @staticmethod
    def validate_interval(seconds: int) -> None: ...   # raise ValidationError if 1..86_399
    def with_interval(self, seconds: int, now: datetime) -> "StatsReportConfig": ...  # validate + anchor=now
```

**Validation rule (FR-008)**: `seconds == 0` (disable) or `seconds >= 86_400` is valid; `1..86_399`
raises a domain `ValidationError` (surfaced as 422 with an actionable message), leaving the stored value
unchanged.

### 2.3 `HourHistogram` (new value object)

```python
@dataclass(frozen=True, slots=True)
class HourHistogram:
    counts: tuple[int, ...]   # exactly 24 entries, index = UTC hour 00..23

    @staticmethod
    def from_hour_counts(pairs: Mapping[int, int]) -> "HourHistogram": ...  # missing hours -> 0
    @property
    def total(self) -> int: ...     # sum == scope's qualifying-send total (SC-005)
```

Always **24 buckets**; an empty scope (zero-send user, or empty system) yields all-zeros (FR-015, edge
cases).

### 2.4 `ReportScope` (new)

A small descriptor pairing a histogram with its recipient + label: `personal` (one user's own sends) or
`global` (all users, admin included). Drives the email subject/title and which recipients exist.

---

## 3. Aggregation read-path (no persisted aggregate)

The per-hour aggregate is **derived, not stored** (Key Entities: "not necessarily persisted"). Computed
on the **prefork `cpu`** worker via the sync engine.

### 3.1 Source-of-truth query (per-user-per-hour)

```sql
SELECT d.user_id,
       EXTRACT(HOUR FROM dt.at AT TIME ZONE 'UTC')::int AS hour,
       COUNT(*) AS sends
FROM delivery_transition dt
JOIN delivery  dl ON dl.id = dt.delivery_id
JOIN dispatch  d  ON d.id  = dl.dispatch_id
WHERE dt.to_status = 'sent'
  AND d.user_id IS NOT NULL      -- exclude server-originated report sends (FR-020, SC-009)
GROUP BY d.user_id, hour;
```

- "Reached at least `sent`" ⇔ a `delivery_transition` with `to_status='sent'` exists (FR-012). One such
  row per qualifying delivery (written once by `record_sent`). Pre-send `queued→failed` and still-`queued`
  rows have no `sent` transition ⇒ excluded for free (SC-006).
- `AT TIME ZONE 'UTC'` ⇒ hour-of-day is UTC-stable regardless of DB session tz (timezone-independence).
- **Global** = the same data summed over all users (admin included — no double-count), still filtered
  `user_id IS NOT NULL` so report sends never inflate it. Can be a sibling aggregate (`GROUP BY hour`) or
  summed from the per-user grid.
- **Report emails contribute nothing** — they are written as **server-owned** rows (`user_id IS NULL`) and
  the `user_id IS NOT NULL` filter excludes them, so the histogram cannot inflate recursively (FR-020,
  SC-009).

### 3.2 Account list for fan-out

```sql
SELECT id, email, is_admin FROM user_account;
```

Left-joining this against the per-user grid guarantees **every** account gets a histogram, all-zero if it
has no `sent` rows (FR-015, SC-003). The admin additionally gets the global histogram (FR-016, SC-004).

### 3.3 Repositories (`SyncReportAggregationRepository`, sync engine)

- `per_user_hour_counts() -> Mapping[UUID, Mapping[int, int]]` — the grid above.
- `global_hour_counts() -> Mapping[int, int]` — global per-hour totals.
- `list_accounts() -> Sequence[AccountRef]` — `(id, email, is_admin)` for fan-out.

`StatsConfigRepository` has an **async** impl (API GET/POST) and a **sync** impl (Beat tick / cycle):
`get() -> StatsReportConfig` (reads/creates the singleton) and `set_interval(seconds, anchor_at)` /
`advance_anchor(anchor_at)`.

---

## 4. Persisted report send (server-originated)

The **stats-report** is application-defined and non-user-definable, but it is **persisted like any other
send** — reusing the 003 lifecycle, not a separate model:

- Each report is a **server-owned `dispatch`** (`user_id = NULL`, `channel = 'report'`, `title`/`content`,
  `attachment_png` = the rendered PNG) with **one `delivery`** (`destination` = the account's email,
  `contact_id = NULL`) and the full append-only `delivery_transition` history.
- It runs through the **existing resilient delivery path** — retry/backoff + per-destination circuit
  breaker + idempotency key (the per-`delivery_id` claim already keys on (cycle, account, scope), since each
  report is its own delivery row) + the `queued → sent → delivered | failed` lifecycle. Direct SMTP returns
  no receipt, so a report **rests at `sent`** (FR-019: *generated and dispatched*).
- Because the dispatch is **server-owned** (`user_id IS NULL`), the report is **excluded from every
  aggregation** and **never appears in any user's send-history** (both filter by `user_id`) — no recursion
  (FR-020, SC-009), no per-row bookkeeping.
- Scheduling state lives on `stats_report_config.anchor_at`, not on any per-recipient record.

---

## 5. Entity relationship summary

```text
user_account (1) ──< dispatch (1) ──< delivery (1) ──< delivery_transition   [003 — read for aggregation]
   │  + is_admin (NEW)                                     │ to_status='sent' → UTC-hour bucket
   │
   └─ (seeded admin: is_admin=true, is_verified=true)

stats_report_config  [NEW singleton: interval_seconds, anchor_at]  ── drives ──>  Beat tick → cycle

Report (server-owned): HourHistogram(24) ─matplotlib─> PNG ─> dispatch(user_id NULL,'report',attachment_png)
                       ─> delivery(dest=account.email) ─> resilient deliver ─> SMTP   [persisted; excluded from aggregation & user history]
```

---

## 6. State & scheduling transitions (config-level, not per-recipient)

| Event | Effect on `stats_report_config` | Effect on reporting |
|---|---|---|
| Provisioning (migration `0003`) | `interval_seconds=2592000`, `anchor_at=now()` | Enabled; first report ~30 d later |
| `POST` valid `interval_seconds ≥ 86400` | `interval_seconds=N`, **`anchor_at=now()`** | Next report fires one interval after the change (FR-010, SC-008) |
| `POST` `interval_seconds = 0` | `interval_seconds=0`, `anchor_at=now()` | Disabled — no cycles until re-enabled |
| `POST` `1 ≤ interval_seconds ≤ 86399` | **unchanged** (rejected) | Stored value preserved; actionable 422 (FR-008, SC-002) |
| Beat tick finds `is_due(now)` true | `anchor_at` advanced to `now()` (the claim/fire time — **not** `anchor + interval`; at a ≥ 24 h cadence the ≤ 60 s drift is immaterial) | Cycle runs on `cpu`; emails fan out on `io` |
| Cycle in flight when `POST` changes cadence | new `anchor_at` governs only the **next** decision | In-flight cycle completes under prior settings (edge case) |

---

## 7. Seeded analytics dataset (`backend/scripts/seed.py`)

Standalone, COPY-based bulk insert (sync engine), bypassing the live pipeline (FR-021–FR-023):

- **≈1,000 `user_account`** rows (synthetic emails, argon2 or a fixed hash, `is_verified=true`,
  `is_admin=false`).
- **≈500,000 completed sends**: for each, one `dispatch` (random owner/channel/title), one `delivery`
  (`status='sent'` or `'delivered'`), and **one `delivery_transition` with `to_status='sent'` and an
  explicit `at`** drawn to cover **all 24 UTC hours** and a **range of dates** (no single hour/day holds
  everything — SC distribution checks).
- Inserted directly in completed state (≥ `sent`); **no** idempotency keys / breaker / fan-out tasks.
- Runnable as `uv run python backend/scripts/seed.py` with a configurable N (`--accounts` / `--sends`) for tests.

**Validation hook**: after seeding, the §3.1 query's per-hour totals must exactly match the generated
counts (SC-005/SC-007), and the spread covers 24 hours × multiple dates (SC distribution).
