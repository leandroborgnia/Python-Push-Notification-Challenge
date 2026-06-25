# Phase 0 Research: Notification Template Management & Multi-Channel Sending

All entries resolve a planning unknown. The inherited stack (FastAPI, SQLAlchemy async+sync, Celery/
RabbitMQ, observability, Testcontainers, kind) is fixed by the constitution and not re-litigated here.
Decisions 1–9 below were confirmed with the user on 2026-06-22.

---

## 1. Authentication: hashing, tokens, flow

**Decision**: OAuth2 **password** flow issuing a **PyJWT** HS256 access token; passwords hashed with
**argon2** via `argon2-cffi`. Token carries `sub` (user id), `exp`, `iat`. Verified in a `current_user`
FastAPI dependency that rejects missing/invalid/expired tokens as 401. No refresh token (spec).

**Rationale**: Constitution mandates OAuth2 + PyJWT (python-jose explicitly forbidden) and argon2-or-
bcrypt. argon2 is the modern default and `argon2-cffi` is the reference binding (no `passlib`
indirection, which is largely unmaintained). `python-multipart` is required for the OAuth2 form body.

**Alternatives**: bcrypt (allowed, but argon2 preferred); `passlib[bcrypt]` (adds an unmaintained
layer); session cookies (spec says stateless access token).

## 2. Auth token lifetimes & the email-token model

**Decision**: Access token **30 min**; **email_token** rows for `verify` (**24 h**) and `reset`
(**1 h**), each a single-use opaque random token (hashed at rest), tied to a user and purpose, with
`expires_at` and `consumed_at`. Reset consumption invalidates the old password by re-hashing the new
one; existing access tokens are short-lived so no server-side revocation list is needed.

**Rationale**: Common, safe defaults; single-use + hashed-at-rest avoids token replay and storage
leakage. Short access-token life keeps "log in again on expiry" (spec) cheap without refresh tokens.

**Alternatives**: JWT-encoded verification links (no DB row) — rejected: can't single-use/revoke;
longer access tokens — rejected: no revocation, so keep them short.

## 3. Auth email "real direct path" in dev/test

**Decision**: A `Mailer` **port** with an `aiosmtplib` adapter (`SmtpMailer`). Dev/kind runs an
in-cluster **Mailpit** (SMTP sink + web UI) so verification/reset mail is genuinely sent and viewable.
Tests bind a **fake mailer** and assert the token by reading the `email_token` row via the persistence
port — no real SMTP in the test suite. Auth email is **synchronous-direct** from the API request path
(awaited `aiosmtplib`), never via the Celery dispatch/resilience pipeline (FR-003/FR-005).

**Rationale**: Matches the user's "real but simple, separate path." Mailpit gives a real SMTP hop in dev
without external accounts; token-via-port keeps US1 deterministic and avoids SMTP flakiness in CI. SMTP
isn't the constitution's "external channel HTTP," so respx (HTTP-only) doesn't apply — the port fake is
the right seam.

**Alternatives**: route auth mail through `simulatedEmail` — rejected by clarification (auth ≠
notification); real third-party SMTP in CI — rejected (flaky, secret-bound).

## 4. Simulated channel providers

**Decision**: A separate in-repo **simulated-provider** FastAPI app (`app/provider_sim/main.py`,
deployed as its own kind Deployment from the same image with a different command). Channel adapters call
it over HTTP via a shared `provider_http` client. The provider injects constitution-mandated failure
modes (artificial latency, random errors, HTTP **429**, timeouts) and drives asynchronous confirmation
(see §5). **In tests, usage splits** — respx (an in-process monkeypatch) cannot intercept HTTP made
inside a Celery worker subprocess, so: **in-process** resilience/failure-mode tests mock the outbound
HTTP with **respx**; the **real-worker routing round-trip** runs the actual `provider_sim` on a real
port the worker can reach (see §10).

**Rationale**: The constitution requires the external channel HTTP boundary to be mocked with respx,
which implies channel calls are real HTTP. A real provider service makes dev genuinely exercise the
network + webhook/poll, while respx keeps the in-process resilience tests hermetic and fast. Reusing the
multi-stage image (different command) honors Principle VII and adds no new build.

**Alternatives**: pure in-process fakes (no HTTP) — rejected: dev wouldn't exercise webhooks/polling and
the respx boundary would be fictional; a third-party mock server (e.g., WireMock) — rejected: extra
non-Python infra for no gain.

## 5. Asynchronous delivery confirmation

**Decision**: `sent` is recorded when the provider **accepts** the outbound call. Then:
- **SMS** → a Celery **`io`** task `sms_poll` queries the provider's status endpoint and **re-enqueues
  itself with countdown** (every ~3 s) until a terminal outcome or the **~30 s** poll window elapses; on
  window-elapse it **stops and leaves the record `sent`** (never auto-failed).
- **Email/Push** → the provider POSTs to our unauthenticated **webhook route**; the handler records the
  outcome via the async repo.

Both paths correlate via the delivery's stored **provider reference** and are **idempotent**: a repeated
or already-terminal confirmation is ignored (no overwrite, FR-025); an uncorrelated callback is ignored
without state change. There is **no confirmation deadline** — absent an outcome a delivery stays `sent`
indefinitely.

**Rationale**: Directly encodes the spec's channel-specific confirmation model. Self-re-enqueuing beats
Celery Beat for a bounded per-delivery poll (no global schedule, state travels with the task args).
Idempotency by correlation is the only integrity guard the unauthenticated webhook needs (§7).

**Alternatives**: Celery Beat periodic sweep for SMS — rejected (coarse, global, harder to bound per
delivery); long-poll/hold-open request — rejected (ties up a worker thread).

## 6. Resilience: retry, circuit breaker, idempotency

**Decision** (per the user's "library if it does it well; hand-roll where it merits"):
- **Retry/backoff** → **tenacity** (`stop_after_attempt(3)`, `wait_exponential(multiplier=0.5)` +
  jitter, retry on transient channel errors/429/timeout).
- **Circuit breaker** → **pybreaker** (`CircuitBreaker(fail_max=5, reset_timeout=30)`), one instance
  **per channel/destination** held in a registry; thread-safe for the threads-pool worker; listeners
  emit structlog/OTel on state change.
- **Idempotency** → **hand-rolled**: a deterministic idempotency key per (dispatch, recipient) persisted
  in `idempotency_key` with a **unique constraint**; the delivery use case claims the key before calling
  the channel and treats a duplicate claim as "already delivered," so retries never double-send.

All three live in `application/` (framework-free), wrapping the `ChannelPort` call; adapters stay dumb.

**Rationale**: tenacity and pybreaker are the mature, community-standard choices and are well-suited
(sync, thread-safe) to the I/O worker. Idempotency is domain-specific (it keys on our dispatch/recipient
identity and uses Postgres as the source of truth) — no library models it better, and hand-rolling keeps
the demonstration explicit.

**Alternatives**: Celery `autoretry_for`/`retry_backoff` — rejected: hides resilience outside the
hexagon and isn't unit-testable without a broker; `purgatory`/`aiobreaker` — viable but pybreaker is more
established for the sync path; a library idempotency layer — none fit the dispatch/recipient keying.

## 7. Webhook endpoint security

**Decision**: The delivery-confirmation webhook endpoints are **unauthenticated** machine-to-machine
routes, **exempt from FR-006**'s user-token rule (a user token is impossible here — the caller is the
provider). Integrity rests on **correlation + idempotency**: only a callback that matches a known
delivery's provider reference is applied, duplicates are ignored, and an unknown reference is dropped
without state change. A real deployment would add a server cert / API key; the simulation omits it
(clarified 2026-06-21).

**Rationale**: Faithful to the clarified simulation contract; avoids inventing auth the spec excluded
while still preventing state corruption.

**Alternatives**: shared-secret HMAC header — out of scope per clarification; reusing the user token —
impossible for provider-originated calls.

## 8. Lifecycle persistence (append-only)

**Decision**: `delivery` holds the current status + provider ref + failure reason; **every** transition
is an append-only `delivery_transition` row (`from_status`, `to_status`, `reason?`, `at`, `attempt?`).
Pre-send validation failures write `queued → failed` **directly** (no `sent`) with a reason; there is no
`skipped` status. Status queries (FR-027) read current status + the transition history.

**Rationale**: Constitution Principle IV mandates append-only, never-overwritten transitions; a separate
transition table is the clean, queryable encoding and makes SC-006 observable.

**Alternatives**: a single mutable status column — rejected (loses history, violates append-only);
event-sourcing the whole domain — rejected (disproportionate).

## 9. API conventions

**Decision**: Routes under **`/api/v1`**. List endpoints (contacts, templates, sends) use simple
**offset/limit** pagination with sane defaults (e.g., `limit=50`, max `100`). DTOs are Pydantic v2 in
`api/schemas.py`; ownership errors return **404** (not 403) to avoid leaking existence across users;
auth failures return **401**; validation/invalid-send return **400/422** with an actionable message.

**Rationale**: Conventional, low-risk, and matches the spec's ownership/observability requirements
(404-on-foreign avoids the cross-user information leak SC-003 cares about).

**Alternatives**: cursor pagination — rejected (overkill at this scale); 403 for foreign resources —
rejected (leaks existence).

## 10. Test strategy: respx vs real worker, and DB isolation

**Decision**: Constitution V mandates **both** (a) respx-mocked external channel HTTP and (b) real-worker
routing tests against a real broker. These **cannot coexist in one test**: respx is an in-process
monkeypatch and cannot intercept HTTP issued from a Celery worker **subprocess**. So they are satisfied
by **different** tests:
- **Resilience/failure-mode** (429/timeout/error → retry/backoff/breaker/idempotency): run
  `application/delivery.py` **in-process** (no worker) with **respx**. This is the constitution's
  respx-mocked boundary, and it's where precise failure injection matters.
- **Routing round-trip** (fan-out → real `io` worker consumes from real RabbitMQ): drive a **real
  `io` worker subprocess** against the **real in-test `provider_sim`** (success path) on a reachable
  port. This is the constitution's real-broker/real-worker mandate; respx is not involved.

**DB isolation**: API/in-process tests use **transaction-rollback** (shared connection + nested
SAVEPOINT per test). Rows written by a worker **subprocess** can't be rolled back from the test's
connection, so those tests clean up by **truncation** (mirrors the 001 pattern).

**Rationale**: Honors both constitution V mandates without pretending respx reaches a subprocess; keeps
failure-mode tests fast/deterministic while still proving real routing end-to-end.

**Alternatives**: Celery eager mode — **forbidden** by constitution V; running everything through the
worker with a real provider for failure tests — rejected (non-deterministic failure injection).

---

### Open items intentionally left to implementation

- Exact structlog field names / OTel span names for resilience events (follow existing telemetry style).
- provider_sim failure-injection probabilities/latency distribution (tunable via its own settings;
  defaults chosen to make retry/breaker tests deterministic via respx, not the live provider).
- Pydantic DTO field-level niceties (examples, regex for phone) — captured in contracts, refined in code.
