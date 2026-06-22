# Phase 1 Data Model: Notification Template Management & Multi-Channel Sending

Shipped as Alembic revision `0002_notification_domain` (single revision, all tables). ORM models live in
`backend/app/adapters/persistence/models.py` and are **shared** by the async (API) and sync (Celery)
engines; engines/sessions are not shared. Domain entities in `domain/` are separate, framework-free
shapes — these tables are persistence detail behind repository ports.

Conventions: PKs are `uuid` (server default `gen_random_uuid()`); timestamps are `timestamptz` with
`server_default now()`; all FKs indexed; soft enums via `CHECK` constraints (kept in-app as `str` enums)
to avoid Postgres `ENUM` migration friction.

---

## Entity overview & relationships

```text
user_account 1───* contact
user_account 1───* template            template *───* contact   (via template_recipient)
user_account 1───* email_token
user_account 1───* dispatch            template ──(snapshot copy, NO FK)──> dispatch
dispatch     1───* delivery            delivery ──> contact (recipient, FK, nullable on snapshot keep)
delivery     1───* delivery_transition (append-only)
delivery     1───1 idempotency_key     (claim row; unique per dispatch+recipient)
```

Key invariant: **`dispatch` holds NO foreign key to `template`** (FR-030). It stores a standalone
snapshot, so editing/deleting the template never alters past sends.

---

## user_account

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| email | text | stored **lowercased** (normalized in app); case-insensitive **unique via functional index `lower(email)`** — no `citext` extension (works with `Base.metadata.create_all` in tests); `EmailStr` at API |
| password_hash | text | argon2 (argon2-cffi); never reversible (FR-002) |
| is_verified | bool | default `false`; gates token issuance (FR-003) |
| created_at | timestamptz | |

- **Rules**: unique email (FR-001); login refused until `is_verified` (FR-003/Acc US1.2).
- Domain: `UserAccount(id, email, is_verified)` — hash stays in the persistence/security layer.

## email_token

Single-use token for `verify` and `reset` (FR-003/FR-005).

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| user_id | uuid FK→user_account | indexed |
| purpose | text | `CHECK in ('verify','reset')` |
| token_hash | text | hash of the opaque token e-mailed to the user (not stored in clear) |
| expires_at | timestamptz | verify = +24 h, reset = +1 h |
| consumed_at | timestamptz null | set on use → single-use |

- **Rules**: valid only if `consumed_at IS NULL AND now() < expires_at`. Consuming a `reset` token
  re-hashes the password; the previous password no longer works (FR-005).

## contact

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| owner_id | uuid FK→user_account | indexed; privacy boundary (FR-010) |
| display_name | text | required |
| email | text null | optional destination |
| phone | text null | optional destination |
| device_token | text null | optional destination |
| created_at | timestamptz | |

- **Rules**: at least one destination required at add (FR-008); private to owner (FR-010, SC-003).
  Add + list only — no modify/delete endpoint this version (spec Assumption).

## template

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| owner_id | uuid FK→user_account | indexed |
| title | text | required |
| content | text | SMS: `CHECK length ≤ 160` enforced in app at create/modify (FR-018); also DB check |
| channel | text | `CHECK in ('email','sms','push')` (FR-016) |
| created_at / updated_at | timestamptz | |

- **Rules**: recipients drawn from owner's contacts; every referenced contact must be owned (FR-011,
  Acc US2.5). Editing never sends (FR-017). SMS content > 160 rejected at save (FR-018).

## template_recipient  (association)

| Column | Type | Notes |
|---|---|---|
| template_id | uuid FK→template | PK part; `ON DELETE CASCADE` |
| contact_id | uuid FK→contact | PK part |

- Composite PK `(template_id, contact_id)`; the template's stored recipient set (FR-015).

## dispatch  (the send snapshot — NO link to template)

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| user_id | uuid FK→user_account | initiating user; ownership for status queries (FR-027) |
| channel | text | `CHECK in ('email','sms','push')` — **snapshot** |
| title | text | **snapshot** of template title at send time |
| content | text | **snapshot** of template content |
| created_at | timestamptz | time of send |

- **Rules**: standalone snapshot; **no FK to template** (FR-030). Each user-initiated send = one new
  dispatch; re-sends are independent (FR-019/FR-026). Recipient snapshot is captured per-delivery below.

## delivery  (per-recipient send record)

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| dispatch_id | uuid FK→dispatch | indexed; `ON DELETE CASCADE` |
| contact_id | uuid FK→contact null | recipient (kept for trace; snapshot fields below are authoritative) |
| recipient_name | text | snapshot of contact name |
| destination | text null | snapshot of the channel-relevant destination (email/phone/device_token) |
| status | text | `CHECK in ('queued','sent','delivered','failed')` — current state |
| failure_reason | text null | set on `failed` (`missing_destination`/`invalid_format`/`invalid_device_token`/`channel_error`/…) |
| provider_ref | text null | correlation id returned by the provider on accept; matches webhook/poll |
| created_at / updated_at | timestamptz | |

- **Rules**: lifecycle below; `failure_reason` required whenever `status='failed'` (FR-022/FR-025).
  `provider_ref` set when `status` reaches `sent`; used to correlate async confirmation (FR-031).

## delivery_transition  (append-only history)

| Column | Type | Notes |
|---|---|---|
| id | bigint PK autoincr | |
| delivery_id | uuid FK→delivery | indexed |
| from_status | text null | null for the initial `queued` |
| to_status | text | one of the four states |
| reason | text null | failure reason / note |
| attempt | int null | retry attempt number when relevant |
| at | timestamptz | `server_default now()` |

- **Rules**: **append-only**, never updated/deleted (Principle IV, FR-025). One row per transition;
  status queries return current `delivery.status` + ordered transitions (SC-006).

## idempotency_key  (hand-rolled dedupe)

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| delivery_id | uuid FK→delivery | indexed |
| key | text | deterministic per (dispatch, recipient) |
| created_at | timestamptz | |

- Constraint: **`UNIQUE(key)`** (and `UNIQUE(delivery_id)`). The delivery use case inserts the claim
  before invoking the channel; a unique-violation means a retry already delivered → no second send
  (FR-024/FR-026, SC-007). Idempotency is scoped to **one send's retries**, never across sends.

---

## Delivery lifecycle state machine

```text
                       ┌─────────────────────────── pre-send validation fails ──┐
                       │            (missing_destination / invalid_format /      │
                       │             invalid_device_token)                       ▼
   (create)  ──▶  queued ──▶ sent ──▶ delivered            queued ─────────▶ failed
                              │  ▲        (provider confirms OK)                 ▲
                              │  └── retry (tenacity, attempt n)                 │
                              └────────────────────── provider confirms fail ───┘
                                       or retries exhausted / breaker open ──────┘
```

- `queued → sent`: provider **accepts** the outbound call (`provider_ref` recorded).
- `queued → failed` (**direct, skips `sent`**): pre-send validation failure, with reason.
- `sent → delivered | failed`: **async** confirmation — SMS poll (bounded) or email/push webhook.
- `sent` may persist **indefinitely** (no confirmation deadline); SMS poll window only stops polling.
- Retries (≤ 3) and the per-channel/destination breaker operate **before** `sent`/around the provider
  accept; idempotency guarantees at most one accepted send per delivery.
- All edges append a `delivery_transition`; none overwrite a recorded terminal state.

## Validation summary (traceability)

| Rule | Source | Enforced at |
|---|---|---|
| Unique email | FR-001 | DB unique + API 409 |
| Password not recoverable | FR-002 | argon2 hashing (security adapter) |
| Verify-before-token | FR-003 | login use case |
| SMS content ≤ 160 | FR-018 | template use case + DB CHECK |
| Channel ∈ {email,sms,push} | FR-016 | DB CHECK + DTO enum |
| Recipient contacts owned by user | FR-011/US2.5 | template use case (ownership query) |
| Send requires channel + ≥1 recipient | FR-029 | sending use case (400) |
| Missing destination → failed(reason), batch continues | FR-022 | delivery use case |
| Append-only transitions | FR-025 | transition table (insert-only) |
| No duplicate delivery on retry | FR-024 | idempotency_key unique |
| Dispatch has no template link | FR-030 | no FK; snapshot columns |
| Cross-user access denied | FR-007/SC-003 | repo scoping by owner_id + 404 |
