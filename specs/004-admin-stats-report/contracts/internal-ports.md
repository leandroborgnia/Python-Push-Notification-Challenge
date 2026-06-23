# Internal Contracts: Admin Stats-Report

**Feature**: `004-admin-stats-report` | **Date**: 2026-06-22

The public HTTP surface is in [`admin-stats-api.yaml`](./admin-stats-api.yaml). This file pins the
**internal ports** (Principle II seams) the feature adds and the **background-task contracts**. Signatures
are illustrative Python 3.13 (`from __future__ import annotations`); the binding happens in `bootstrap.py`
(API) and `tasks/deps.py` (worker).

---

## 1. Report email channel (new `ChannelPort`) + `Payload` attachment — `app/adapters/channels/report_email/`

The report-email seam, and **deliberately the seed of the future real (non-simulated) email channel**. It
is a **`ChannelPort`** (not a separate port) so reports flow through the **existing resilient delivery
pipeline** (`DeliveryService`: retry/backoff + breaker + idempotency + persisted lifecycle). Adding it is
**one new adapter** + a bootstrap binding — no edits to existing channel adapters (**SC-010**).

```python
# app/domain/channels.py — extend the enum
class Channel(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    REPORT = "report"     # NEW — server-originated stats-report email

# app/ports/channels.py — extend the shared Payload (one-time attachment capability)
@dataclass(frozen=True, slots=True)
class Payload:
    title: str
    content: str
    attachment: bytes | None = None        # NEW — e.g. the 24-bar PNG; existing adapters ignore it
    attachment_name: str = "report.png"    # NEW

class SmtpReportEmailChannel:               # implements ChannelPort, channel = Channel.REPORT
    def destination_of(self, contact): ...               # n/a — the cycle sets `delivery.destination`
    def validate(self, destination, payload): ...        # email-format check → ChannelValidationError
    def send(self, destination, payload, idempotency_key) -> SendResult:
        # stdlib smtplib: build a multipart EmailMessage, attach payload.attachment (if any),
        # From = settings.report_mail_from or settings.mail_from; send to settings.smtp_host:smtp_port.
        # Raise TransientChannelError on a transient SMTP failure (drives retry/backoff/breaker),
        # PermanentChannelError on a permanent one. Returns SendResult(provider_ref=<message-id>).
    def confirmation_mode(self) -> ConfirmationMode:
        return ConfirmationMode.WEBHOOK     # no webhook ever arrives → the report rests at `sent`
    def poll_status(self, provider_ref): ...             # n/a
```

- **Attachment threading**: `DeliveryService` builds
  `Payload(title=…, content=…, attachment=dispatch.attachment)` — a one-time additive change to the shared
  flow (existing channels leave `attachment=None`).
- **Test doubles**: a **local `aiosmtpd` sink** captures the SMTP send in worker round-trip tests; an
  **injectable failing report `ChannelPort`** drives the in-process resilience test.

---

## 2. `GraphRenderer` port (new) — `app/ports/graph.py`

Isolates matplotlib behind a port so `application/` never imports a plotting library.

```python
class GraphRenderer(Protocol):
    def render_hour_histogram(self, counts: Sequence[int], *, title: str) -> bytes:
        """Render a 24-bar bar chart (x = UTC hour 00..23, y = count) to PNG bytes.
        `counts` MUST have length 24. Returns a non-empty PNG (\\x89PNG... header)."""
```

- **Impl**: `adapters/graphing/matplotlib_renderer.py :: MatplotlibGraphRenderer` — `matplotlib.use("Agg")`
  before importing `pyplot`; renders 24 bars, axis labels `00..23`, the scope title; returns
  `BytesIO.getvalue()`. Runs on the **prefork `cpu`** pool.
- **Contract checks**: length-24 input; output starts with the PNG magic bytes and is non-empty
  (renderer unit test).

---

## 3. Stats-config repositories (new) — `app/ports/repositories.py`

Two impls of the same shape: **async** for the API (asyncpg), **sync** for the Beat tick/cycle (psycopg).

```python
class StatsConfigRepository(Protocol):           # async variant: methods are async
    def get(self) -> StatsReportConfig: ...        # reads/creates the singleton (id=1)
    def set_interval(self, seconds: int, anchor_at: datetime) -> StatsReportConfig: ...
    def advance_anchor(self, anchor_at: datetime) -> None: ...  # after a fired cycle
```

- Async impl: `adapters/persistence/async_repo.py :: AsyncStatsConfigRepository`.
- Sync impl: `adapters/persistence/sync_repo.py :: SyncStatsConfigRepository`.
- `set_interval` enforces the singleton (`UPDATE ... WHERE id = 1`); never inserts a second row.

---

## 4. `SyncReportAggregationRepository` (new) — sync engine only

```python
class SyncReportAggregationRepository(Protocol):
    def per_user_hour_counts(self) -> Mapping[UUID, Mapping[int, int]]: ...  # {user_id: {hour: sends}}
    def global_hour_counts(self) -> Mapping[int, int]: ...                    # {hour: sends}, all users
    def list_accounts(self) -> Sequence[AccountRef]: ...                      # (id, email, is_admin)

class SyncReportSendRepository(Protocol):     # creates the server-owned report rows the cycle delivers
    def create_report_delivery(
        self, *, to_email: str, subject: str, body: str, png: bytes
    ) -> UUID: ...    # INSERT server-owned dispatch (user_id NULL, channel='report', attachment_png=png)
                      #   + queued delivery (destination=to_email, contact_id NULL) + queued transition;
                      #   returns the new delivery_id (enqueued to the existing `deliver` task).
```

- Impls in `adapters/persistence/sync_repo.py`.
- The aggregation queries run the §3 query from [data-model.md](../data-model.md)
  (`delivery_transition.to_status='sent'`, `EXTRACT(HOUR FROM at AT TIME ZONE 'UTC')`, **filtered
  `dispatch.user_id IS NOT NULL`** so server-owned report sends never count). Accounts absent from the grid
  → all-zero histogram via `list_accounts` left-join in `application/`.

---

## 5. `StatsConfigService` (application, async) — `app/application/stats_config.py`

Backs the admin endpoints.

```python
class StatsConfigService:
    async def get_frequency(self) -> FrequencyView: ...                # (interval_seconds, enabled)
    async def set_frequency(self, interval_seconds: int) -> FrequencyView: ...
        # StatsReportConfig.validate_interval -> ValidationError (->422) on 1..86399;
        # else persist + reset anchor_at = clock.now(); 0 disables.
```

- `ValidationError` from the domain maps to **HTTP 422** with an actionable message; the stored value is
  left unchanged (FR-008, SC-002).

---

## 6. `ReportCycleService` (application, sync) — `app/application/reporting.py`

The CPU-bound cycle body (called from the `cpu` task). Framework-free; uses the aggregation repo,
`GraphRenderer`, the `SyncReportSendRepository`, and an injected `enqueue_deliver` callback (the existing
`app.tasks.sending.deliver` in prod; a capture in tests).

```python
class ReportCycleService:
    def run_cycle(self) -> ReportCycleResult:
        """1) load per-user + global hour grids and the account list (one aggregation pass);
           2) for each account: render its personal 24-bar PNG -> create a server-owned report
              dispatch/delivery -> enqueue `deliver(delivery_id, 'report')` on the io queue;
           3) for the admin: also render the GLOBAL PNG -> a second report delivery -> enqueue;
           4) return counts (accounts served, deliveries enqueued) for telemetry.
        Zero-send accounts get an all-zero histogram (still rendered + delivered)."""

class ReportDueService:                 # used by the tick before run_cycle
    def claim_if_due(self, now: datetime) -> bool:
        """True (and sets anchor_at = now(), the claim time) iff config.is_due(now); else False."""
```

- The admin receives **exactly two** reports per cycle: personal + global (SC-004).
- Global histogram includes the admin's own sends, never double-counted (edge case).
- Each report is delivered by the **existing** resilient `deliver` task — breaker + idempotency +
  persisted `queued→sent` lifecycle; a persistent failure is isolated as `queued→failed` (FR-019).

---

## 7. Celery task contracts — `app/tasks/reporting.py`

| Task | Queue / pool | Trigger | Body |
|---|---|---|---|
| `app.tasks.reporting.stats_report_tick` | `cpu` / prefork | Beat, every `stats_report_due_check_interval_s` (60 s) | If `ReportDueService.claim_if_due(now)`: run `ReportCycleService.run_cycle()` (aggregate + render on CPU), persisting a server-owned report `dispatch`/`delivery` per recipient and **enqueuing the existing `app.tasks.sending.deliver(delivery_id, 'report')` on `io`**. No-op when disabled or not yet due. |

Report delivery itself reuses the **existing** `app.tasks.sending.deliver` (`io` / threads) →
`DeliveryService.deliver_one`: retry/backoff + per-destination breaker + idempotency + the persisted
`queued → sent → delivered | failed` lifecycle. A failure that persists after retries is recorded
`queued → failed`, logged + telemetry-surfaced, and isolated — it does not affect other recipients
(FR-019, SC-003). The report rests at `sent` (the report channel's `confirmation_mode` is WEBHOOK but no
webhook arrives). **No new `send_report_email` task is added.**

**Beat schedule** (in `tasks/celery_app.py`):

```python
app.conf.beat_schedule = {
    "stats-report-due-check": {
        "task": "app.tasks.reporting.stats_report_tick",
        "schedule": settings.stats_report_due_check_interval_s,  # 60.0
        "options": {"queue": "cpu"},
    }
}
```

**Message payload note**: the rendered PNG is stored on the report `dispatch` row, so the `deliver`
message carries only the `delivery_id` (the io worker reads the PNG from the dispatch) — no large base64
payloads through RabbitMQ (research §6).

---

## 8. `current_admin` dependency — `app/api/deps.py`

```python
async def current_admin(container, user_id: CurrentUser) -> UUID:
    """Resolve current_user (401 on bad/absent token), load the account, require is_admin.
    Raise 403 'admin privileges required' for an authenticated non-admin."""
```

- Mounted on the admin router (`/api/v1/admin/...`). Ordinary endpoints keep using `current_user`, so the
  admin retains every ordinary capability and gains no cross-user access (FR-004).
- 401 (unauthenticated) vs 403 (authenticated non-admin) split is the only new authz rule (FR-005).
