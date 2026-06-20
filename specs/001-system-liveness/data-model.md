# Phase 1 Data Model: System Liveness Walking Skeleton

Two kinds of model: one **persisted** table (the only DB schema this slice adds) and several
**in-memory DTOs** for the health responses (not persisted). Maps spec Key Entities → concrete shapes.

## Persisted

### `LivenessCompletion` (table: `liveness_completion`)

The correlation-keyed completion record written by the smoke-check task (worker, **sync** engine) and
read back by the smoke-check use case (**async** engine). Created by Alembic revision
`0001_liveness_completion`. Shared ORM class in `adapters/persistence/models.py`.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | `BIGINT` | PK, identity | Surrogate key. |
| `correlation_id` | `UUID` | NOT NULL, indexed | One value per smoke-check invocation (UUID4). |
| `pool_label` | `TEXT` | NOT NULL, `CHECK (pool_label IN ('cpu','io'))` | Which pool processed the task. |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, server default `now()` | When the worker wrote the row. |

- **Unique**: `(correlation_id, pool_label)` — one completion per pool per invocation (idempotent under
  accidental re-delivery).
- **Index**: `(correlation_id)` — supports the reader's "did both pools complete for this run?" query.
- **Lifecycle**: insert-only for this slice (no updates/deletes in app code). Rows are disposable
  liveness evidence; pruning/retention is out of scope.
- **Engine usage**: WRITE via `sync_repo.py` (psycopg v3, in the Celery task); READ via `async_repo.py`
  (asyncpg, in the API/CLI). The ORM model is shared; engines/sessions are not.

**Validation / rules**
- `pool_label` constrained to the two architecture-defined pools.
- Reader success condition: for a given `correlation_id`, rows exist for **both** `'cpu'` and `'io'`
  within the bounded timeout (`smoke_timeout_s`).

## In-memory DTOs (not persisted)

### `HealthStatus` (domain enum)
`HEALTHY` | `NOT_HEALTHY` — the binary verdict (spec FR-002). For `/livez` a process-level
`ALIVE` is reported; no degraded/partial state in this slice.

### `SubsystemCheck` (domain value object)
Result of one shallow check inside `/health`.

| Field | Type | Notes |
|-------|------|-------|
| `name` | enum: `data_store` \| `message_broker` \| `worker_pool_cpu` \| `worker_pool_io` | Subsystem identifier (no `task_result_store` — removed, results disabled). |
| `passed` | bool | Pass/fail. |
| `detail` | str \| null | Optional reason / elapsed ms / error summary. |

### `ReadinessReport` (domain aggregate)
Returned by `/health`.

| Field | Type | Notes |
|-------|------|-------|
| `status` | `HealthStatus` | `HEALTHY` only if **every** `SubsystemCheck.passed` (FR-002). |
| `checked_at` | datetime (UTC) | Timestamp of the aggregate evaluation. |
| `checks` | list[`SubsystemCheck`] | One per subsystem; always present in the body (FR-005). |

- HTTP mapping (api/schemas.py → Pydantic): `HEALTHY` → `200`, `NOT_HEALTHY` → `503`, body always
  serializes `status`, `checked_at`, `checks[]`.

### Probe ports (contracts the adapters satisfy)
- `BrokerProbe.check() -> SubsystemCheck` (broker reachability; async-wrapped blocking call).
- `WorkerProbe.check() -> list[SubsystemCheck]` (per-pool ping → `worker_pool_cpu`, `worker_pool_io`).
- `LivenessCompletionWriter.record(correlation_id, pool_label)` — **sync** (worker).
- `LivenessCompletionReader.both_completed(correlation_id) -> bool` — **async** (API/CLI).

## Mapping to spec Key Entities

| Spec entity | This model |
|-------------|-----------|
| Readiness Report | `ReadinessReport` DTO |
| Subsystem Check Result | `SubsystemCheck` DTO (data store, broker, cpu pool, io pool) |
| Background Liveness Task | Celery `liveness_ping(correlation_id, pool_label)` in `tasks/liveness.py` |
| Completion Record | `LivenessCompletion` table |
