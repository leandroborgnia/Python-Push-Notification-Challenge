# Feature Specification: Admin Account & Server-Wide Stats-Report

**Feature Branch**: `004-admin-stats-report`

**Created**: 2026-06-22

**Status**: Draft

**Input**: User description: "One new default admin account (recognizable at server creation, through migrations or similar; accounts can now be admin or not, but no endpoints to promote/demote — out of scope) can do anything any other account can do, but also can set one more configuration through endpoints `/admin/stats-report/frequency` (GET and POST) controlling the amount of time between each server-wide stats-report. A stats-report is a special notification that cannot be defined by people and is self-defined by the application, sent through mail (using the mails of each account), containing a bar graph with 24 bars — one per hour of the day — showing the number of notifications sent in each hour regardless of which day. The admin receives the graph accumulated across all users; each user receives the one accumulated by themselves. The graph is made with a Python visual graph library. We also need a way to seed the data (≈500K notifications sent from ≈1000 users total); the seeding process can be as simple as needed."

## Clarifications

### Session 2026-06-22

- Q: What is the admin's privilege scope? → A: The admin is an **ordinary user** (its own contacts, templates, sends, status queries) **plus** the stats-report-frequency control and receipt of the global report. It has **no cross-user data access** — it cannot read, modify, delete, or send another user's resources. There are no endpoints to grant or revoke admin status.
- Q: What does each bar count, and which timestamp buckets it? → A: A bar counts every **per-recipient delivery that reached at least the `sent` state** (i.e., was accepted by its channel). Deliveries that never reached `sent` — including pre-send validation failures that go `queued → failed` directly — are **not** counted. Each qualifying send is bucketed by the **UTC hour-of-day (00–23)** of the moment it was sent, aggregated across **all dates** (the calendar day is ignored; only the hour matters).
- Q: How is the report email delivered? → A: The per-hour **aggregation MUST run on the CPU-bound (prefork) worker pool** — this is the constitution's canonical CPU-bound usage-aggregation task, finally exercised here. After aggregation, the report email is sent through the **same resilient delivery pipeline** as user notifications (retry/backoff + circuit breaker + idempotency + persisted lifecycle) via a **new dedicated report-email channel**, addressed directly to each **account's** registered email. It MUST NOT use the plain transactional verification/reset email path. Report recipients are the user accounts themselves, **not** entries from any user's contacts book.
- Q: Who receives a report each cycle, and does the admin also get a personal one? → A: The admin receives **both** a personal report (its own sends, exactly like any user) **and** a global report aggregating all users' sends. Every other user receives a personal report — **including users with zero qualifying sends**, who receive an all-zero 24-bar graph. The global aggregate **includes** the admin's own sends.
- Q: What seed volume governs this feature? → A: Follow the user-stated **≈500,000 sends across ≈1,000 users** (≈500 each). The constitution's Principle III figure ("~1,000 users × ~100,000 events each") is treated as illustrative; 100M is out of scope as too large. Seeded sends are inserted directly in their completed (≥`sent`) state, bypassing the live send/resilience pipeline, and are spread across all 24 UTC hours and many dates.
- Q: Frequency value semantics? → A: A **single, server-wide, persisted** interval (survives restarts). The provisioning **default is 30 days**; the **minimum is 24 hours**; a value of **zero / none disables** reporting; any value below the minimum (other than the disable value) is rejected. **Changing the frequency resets the schedule** — the next report fires one interval after the change.
- Q: Are the report emails themselves counted in the statistics? → A: **No.** Report emails are application-generated system mail, not user notifications; they are excluded from every aggregation so the histogram never inflates recursively.
- Q: Is the stats-report a persisted entity in the send lifecycle, or ephemeral system mail? → A: **Persisted, like any other send.** Report emails ARE recorded as `dispatch`/`delivery`/`delivery_transition` rows and go through the **full resilient delivery path** (retry/backoff + circuit breaker + idempotency + the persisted `queued → sent → delivered | failed` lifecycle). They are **server-originated** (no owning user — `dispatch.user_id` is null), so they are excluded from the histogram (which counts only user-owned sends) and never appear in any user's send-history (filtered by owner). Direct SMTP returns no delivery receipt, so a report rests at `sent` (the guarantee is *generated and dispatched*). Scheduling state (last/next run) lives on the stats-report configuration, not on a per-recipient record.
- Q: Are per-recipient report sends independent, and what does "every user receives a report" guarantee under genuine send failure? → A: **Independent; the guarantee is "generated and dispatched", not "delivered".** Each recipient's report is its own send unit; a failure that persists after retries/backoff is **isolated** (persisted as `queued → failed`) and surfaced via logs/telemetry, and the cycle still serves every other recipient. SC-003's "100% receive" means a report is composed and handed to the resilient send path for 100% of accounts — not that SMTP necessarily confirms delivery.
- Q: How is the frequency value represented in the API and stored? → A: As an **integer number of seconds**. `0` disables reporting; any value ≥ 86,400 (24h) is accepted; values in 1–86,399 are rejected. The provisioning default is 2,592,000 (30 days). GET returns the current integer seconds plus the enabled/disabled state.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Admin account & stats-report frequency control (Priority: P1)

A single default administrator account exists from the moment the server is brought up — recognizable as an admin and usable to sign in without any manual setup step. Beyond everything an ordinary account can do, the admin can read and change one server-wide setting: how often the system emits its stats-report. No other account can read or change this setting, and there is no way for anyone to make another account an admin (or to remove admin status).

**Why this priority**: The admin identity and the single privileged configuration are the gate for the entire feature — the report cadence cannot exist without them, and the authorization boundary must hold before any report is ever sent. It is independently demonstrable on its own.

**Independent Test**: Sign in as the seeded admin; GET `/admin/stats-report/frequency` and observe the default (30 days); POST a new valid interval (≥ 24h) and GET again to confirm it persisted; POST an interval below 24h and confirm rejection; POST the disable value and confirm reporting is reported as disabled. Then confirm an authenticated non-admin receives "forbidden" and an unauthenticated caller receives "unauthenticated" on both verbs.

**Acceptance Scenarios**:

1. **Given** a freshly provisioned server, **When** an operator signs in with the configured admin credentials, **Then** the login succeeds without any email-verification step and the account is recognized as the administrator.
2. **Given** the admin is signed in, **When** they GET the stats-report frequency before any change, **Then** the response reports the default interval of 30 days and that reporting is enabled.
3. **Given** the admin is signed in, **When** they POST a new interval of at least 24 hours, **Then** the new interval is stored, survives a restart, and a subsequent GET returns it.
4. **Given** the admin is signed in, **When** they POST an interval below 24 hours (and not the disable value), **Then** the request is rejected with a clear, actionable error and the stored interval is unchanged.
5. **Given** the admin is signed in, **When** they POST the disable value (zero / none), **Then** reporting is disabled and a subsequent GET reports it as disabled.
6. **Given** an authenticated non-admin user, **When** they call GET or POST on the frequency endpoint, **Then** the request is rejected as forbidden; **When** the caller presents no/invalid token, **Then** it is rejected as unauthenticated.
7. **Given** the admin account, **When** it uses ordinary capabilities (contacts, templates, sending, status queries), **Then** it behaves exactly like any user and **cannot** read, modify, delete, or send any other user's resources.

---

### User Story 2 - Scheduled per-hour notification-volume reports by email (Priority: P1)

On the configured cadence, the system automatically composes and emails a stats-report to everyone. The report is a bar graph with 24 bars — one per hour of the day — where each bar's height is the number of notifications sent in that hour, summed across every date. Each user receives a graph built only from their own sends; the administrator receives that same personal graph **and** a second, server-wide graph aggregating every user's sends. The report is entirely application-defined: no user can author, edit, or alter it — only the cadence is configurable.

**Why this priority**: This is the headline capability — the admin-facing notification type the project deferred from earlier work, and the first exercise of the CPU-bound aggregation the constitution describes. It delivers the core user-visible value of the feature.

**Independent Test**: With a seeded dataset and a test-configured cadence, drive one report cycle; confirm each user account receives an email whose graph has exactly 24 hour buckets reflecting only that user's qualifying sends; confirm a user with no qualifying sends still receives an all-zero graph; confirm the admin receives two reports (personal + global) and that the global bars equal the sum across all users; confirm sends that never reached `sent` contribute zero; confirm each report is persisted as a **server-owned** `dispatch`/`delivery` (with lifecycle transitions) that does **not** appear in any user's send-history and is **not** counted by a subsequent aggregation.

**Acceptance Scenarios**:

1. **Given** reporting is enabled with a configured interval, **When** an interval elapses, **Then** the system emits a stats-report cycle automatically, without any manual trigger.
2. **Given** a report cycle runs, **When** the per-hour aggregation is computed, **Then** it counts every per-recipient delivery that reached at least `sent`, bucketed by the UTC hour-of-day (00–23) of the send, across all dates, and excludes any delivery that never reached `sent`.
3. **Given** a report cycle runs, **When** each user's personal report is built, **Then** it reflects only that user's own sends, and a user with zero qualifying sends receives a graph with all 24 bars at zero.
4. **Given** a report cycle runs, **When** the admin's reports are built, **Then** the admin receives a personal report (its own sends) **and** a separate global report aggregating all users' sends (the admin's own sends included).
5. **Given** any report, **When** it is delivered, **Then** it arrives by email at the recipient **account's** own registered email address (not via any contacts book) and contains the 24-bar graph image.
6. **Given** report emails are sent, **When** a later report cycle aggregates again, **Then** the report emails themselves are **not** counted as notifications (the histogram is unchanged by the act of reporting).
7. **Given** the cadence is disabled, **When** time passes, **Then** no reports are emitted until reporting is re-enabled; **Given** the cadence is changed, **When** the change is saved, **Then** the next report fires one interval after the change.

---

### User Story 3 - Seeded analytics dataset (Priority: P2)

So that the reports and the aggregation are meaningful and exercised at scale, an operator can populate the system with a large, realistic analytics dataset: roughly 1,000 user accounts and roughly 500,000 completed notification-sends, spread across all 24 hours of the day and many dates. The seeding can be as simple as bulk insertion of already-completed sends — it does not need to drive the live sending pipeline.

**Why this priority**: The dataset is what makes the headline report demonstrable and what exercises the CPU-bound aggregation against realistic volume, but it supports the P1 stories rather than standing alone as the headline.

**Independent Test**: Run the seeding capability; verify roughly 1,000 accounts and roughly 500,000 completed send records exist, distributed across all 24 UTC hours and a range of dates; then run a report cycle and confirm the per-hour totals match the seeded data exactly.

**Acceptance Scenarios**:

1. **Given** an empty (or freshly migrated) database, **When** the seeding capability is run, **Then** approximately 1,000 user accounts and approximately 500,000 completed send records are created.
2. **Given** the seeded dataset, **When** the per-hour totals are computed, **Then** the sends are distributed across all 24 UTC hours and across multiple dates (no single hour or single day holds everything).
3. **Given** the seeded send records, **When** they are created, **Then** they are inserted directly in their completed (≥ `sent`) state without passing through the live send/resilience pipeline.
4. **Given** the seeded dataset, **When** a report cycle runs over it, **Then** the aggregation completes and the resulting per-hour totals exactly match the seeded counts.

---

### Edge Cases

- **Disabled cadence**: with the frequency set to the disable value, no report is ever emitted until it is re-enabled; GET clearly reports the disabled state.
- **Below-minimum interval**: a POST of any interval below 24 hours (other than the disable value) is rejected; the previously stored interval is preserved.
- **Empty system**: on a server with no qualifying sends at all, every recipient still receives an all-zero 24-bar graph; the global report is all-zeros too.
- **New user mid-history**: a recently registered user with few or no sends receives a correspondingly sparse or all-zero graph.
- **Date collapsing**: sends from many different calendar dates that share the same hour-of-day collapse into the same bucket — the bar reflects the hour-of-day total regardless of date.
- **Sends that never reached `sent`**: pre-send validation failures (`queued → failed`) and anything still `queued` contribute zero to every bar.
- **Admin double-counting guard**: the admin's own sends appear in its personal report and once in the global report — never excluded from, nor double-counted in, the global aggregate.
- **Cadence change during a cycle**: an in-flight report cycle completes under the prior settings; the new interval governs the next scheduling anchor.
- **Authorization**: any non-admin (authenticated) hitting an `/admin/*` endpoint is forbidden; any unauthenticated caller is rejected as unauthenticated.
- **Timezone independence**: hour bucketing is in UTC and does not depend on any user's local time zone.
- **Large fan-out**: a cycle that must email on the order of ~1,000 recipients does so as resilient background sends without blocking the schedule or the API.
- **Report send failure**: a single recipient whose report send keeps failing after retries/backoff is isolated and surfaced via logs/telemetry; the remaining recipients are still served, and the failure is persisted as a `queued → failed` lifecycle on that recipient's report delivery (a server-owned record, absent from any user's send-history).
- **Re-provisioning the admin**: bringing the server up again does not create a second admin or overwrite/duplicate the existing one (idempotent provisioning).

## Requirements *(mandatory)*

### Functional Requirements

**Admin account & authorization**

- **FR-001**: System MUST provision exactly **one** default administrator account at server creation through a deterministic, idempotent bootstrap (an Alembic data migration or an equivalent startup step), such that the admin exists with no manual post-deploy action and re-provisioning never creates a duplicate or second admin.
- **FR-002**: The default admin account MUST be **pre-verified** (it does not require the email-verification step that ordinary registrations require) and its credentials MUST be supplied via configuration/environment, never hard-coded or committed.
- **FR-003**: Accounts MUST carry an **admin / non-admin** designation that is recognizable by the system. The system MUST NOT expose any endpoint (or other user-facing mechanism) to grant or revoke admin status — promotion/demotion is out of scope.
- **FR-004**: The admin account MUST retain **every** capability of an ordinary account (contacts, templates, sending, status queries) and MUST NOT gain any cross-user data access: it cannot read, modify, delete, or send another user's resources.
- **FR-005**: System MUST expose admin-only endpoints to **read** (GET) and **set** (POST) the server-wide stats-report frequency at `/admin/stats-report/frequency`. Authenticated non-admin callers MUST be rejected as **forbidden**; missing/invalid/expired tokens MUST be rejected as **unauthenticated**.

**Stats-report frequency configuration**

- **FR-006**: The stats-report frequency MUST be a **single, server-wide** setting that is **persisted** and survives restarts (it is not per-user and not in-memory only).
- **FR-007**: The frequency MUST be represented and stored as an **integer number of seconds**. GET MUST return the current interval (in seconds) and whether reporting is currently enabled or disabled (`0` ⇒ disabled).
- **FR-008**: POST MUST validate the submitted integer-seconds value: **`0` disables** reporting; any value **≥ 86,400 (24 hours)** is accepted; any value in **1–86,399** MUST be rejected with a clear, actionable error, leaving the stored value unchanged.
- **FR-009**: The frequency at provisioning MUST default to **2,592,000 seconds (30 days)** with reporting enabled.
- **FR-010**: Changing the frequency MUST **reset the schedule** so the next report fires one interval after the change; while disabled, no reports are produced until reporting is re-enabled.

**Report generation & content**

- **FR-011**: On each elapsed interval the system MUST **automatically** run a report cycle (no manual/on-demand trigger is provided by this feature).
- **FR-012**: The per-hour aggregation MUST count every **per-recipient delivery that reached at least the `sent` state**, bucketed by the **UTC hour-of-day (00–23)** of the send, aggregated across **all dates**; deliveries that never reached `sent` (e.g., `queued`, or `queued → failed` pre-send validation failures) MUST NOT be counted.
- **FR-013**: The aggregation MUST run as **CPU-bound background work on the prefork worker pool** — this is the constitution's canonical CPU-bound usage-aggregation task (per-UTC-hour bucketing for a bar graph).
- **FR-014**: Each report MUST be rendered as a **bar graph of exactly 24 bars** (one per UTC hour-of-day), each bar's height being the count of qualifying sends in that hour, produced with a Python visual-graphing library.
- **FR-015**: For **each** user account the system MUST produce a **personal** report counting only that user's own sends; a user with no qualifying sends MUST still receive an all-zero 24-bar graph.
- **FR-016**: The administrator MUST receive **two** reports per cycle: a **personal** report (its own sends, like any user) and a **global** report aggregating **all** users' sends (the admin's own sends included).
- **FR-017**: Reports MUST be delivered by **email to each account's own registered email address**; recipients are the user accounts themselves and MUST NOT be drawn from any user's contacts book.
- **FR-018**: The stats-report MUST be **application-defined**: no user (including the admin) can create, edit, author, or otherwise define its content — only its **cadence** is configurable.
- **FR-019**: Report emails MUST be delivered through the **same resilient send path** as user notifications, on the I/O worker pool — **retry/backoff, a per-destination circuit breaker, and idempotency keys** — and MUST be **persisted** as `dispatch`/`delivery`/`delivery_transition` records with the full `queued → sent → delivered | failed` lifecycle (a report rests at `sent`, since direct SMTP returns no delivery receipt). They MUST be sent via a **new dedicated report-email channel** that carries the 24-bar graph as an **attachment**, and MUST NOT use the plain transactional verification/reset email path. Report sends are **server-originated** (no owning user), so they never appear in any user's send-history/status queries. Each recipient's report MUST be an **independent** send unit: a failure that persists after retries MUST be isolated (persisted as `queued → failed`, surfaced via logs/telemetry) and MUST NOT abort the cycle for the remaining recipients.
- **FR-020**: Report emails MUST NOT be counted as notification sends in any aggregation. Because report sends are **server-originated** (`dispatch.user_id` is null) and the aggregation counts only **user-owned** sends, report emails are excluded and the histogram cannot inflate recursively — the exclusion is a single `user_id IS NOT NULL` predicate, not per-record bookkeeping.

**Seeding**

- **FR-021**: System MUST provide a **seeding capability** that populates approximately **1,000** user accounts and approximately **500,000** completed notification-send records.
- **FR-022**: Seeded sends MUST be distributed across **all 24 UTC hours** and across a **range of dates**, so that per-hour aggregation and the resulting graphs are non-trivial.
- **FR-023**: Seeded send records MAY be inserted directly in their completed (≥ `sent`) state **without** passing through the live send/resilience pipeline (the seeding process may be as simple as bulk insertion) and MUST be runnable as a standalone operation.

### Key Entities *(include if feature involves data)*

- **Account admin designation**: an attribute on the existing user account marking it admin or non-admin. Exactly one seeded admin exists; the flag cannot be changed through any endpoint.
- **Stats-report configuration**: a single, server-wide, persisted record holding the report **interval as an integer number of seconds**, whether reporting is **enabled/disabled** (`0` ⇒ disabled), and the **scheduling anchor** (e.g., last-run timestamp) that determines when the next report fires. Default interval 2,592,000 s (30 days); minimum 86,400 s (24 hours); `0` turns reporting off.
- **Per-hour send aggregate**: a derived count of qualifying sends (those that reached ≥ `sent`) bucketed into 24 UTC hour-of-day buckets, computed per scope — per user (personal) and across all users (global). The basis for each 24-bar graph; not necessarily persisted.
- **Stats-report**: an application-defined, non-user-definable report for a given scope (one user, or global), realized as a 24-bar graph image delivered by email. Holds no user-authored content; only the cadence is configurable. It is **persisted like any other send** — a **server-owned** `dispatch`/`delivery` (no owning user) with the full append-only lifecycle history — but, being server-originated, it is **excluded from every aggregation** and **never appears in any user's send-history**.
- **Seeded send dataset**: the analytics source — ≈1,000 user accounts and ≈500,000 completed send records spread across all hours and many dates, used to make reports meaningful and to exercise the CPU aggregation at scale.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The seeded admin can read and update the report frequency on a fresh server with no manual setup, and 100% of frequency reads/writes by non-admin or unauthenticated callers are refused.
- **SC-002**: Before any change the reported frequency is 30 days; 100% of attempts to set an interval below 24 hours (other than the disable value) are rejected and leave the stored value unchanged.
- **SC-003**: In a report cycle, a personal report is composed and dispatched for 100% of user accounts (a user with zero qualifying sends still gets a 24-bar all-zero graph); a persistent send failure for one recipient is isolated and never prevents the others from being dispatched.
- **SC-004**: In every report cycle the admin receives exactly two reports — one personal and one global.
- **SC-005**: For any scope, each report's 24 per-hour counts exactly match the underlying qualifying-send data (verifiable against the seeded dataset), and the bars sum to that scope's total qualifying sends.
- **SC-006**: Sends that never reached `sent` contribute zero to every bar of every report (100% excluded).
- **SC-007**: The aggregation completes over the full ≈500,000-record dataset and yields correct per-hour totals for both personal and global scopes.
- **SC-008**: A changed cadence takes effect for the next cycle (the next report fires one interval after the change), and disabling reporting stops all reports until it is re-enabled.
- **SC-009**: Emitting report emails does not change any subsequent histogram — the per-hour totals are identical whether or not reports were sent (no recursion).
- **SC-010**: Adding the report-email **channel** introduces no edits to existing channel adapters or per-channel dispatch logic — the channel boundary stays open for extension (one new adapter + a binding). The feature additionally adds a **one-time attachment capability** to the shared delivery flow (a deliberate, in-scope capability extension that any future channel can use — not a per-channel edit), so channels can now dispatch attachments.

## Assumptions

- **Admin provisioning**: the admin is created by an idempotent bootstrap (Alembic data migration or an equivalent startup step) using credentials from configuration/environment; it is pre-verified and unique. An `is_admin`-style flag is added to the account; no promote/demote endpoints exist (out of scope per the request).
- **Authorization model**: `/admin/*` endpoints require admin role — authenticated non-admins receive forbidden, unauthenticated callers receive unauthenticated. This reuses 003's OAuth2/token authentication.
- **Frequency setting**: one global, persisted interval expressed as an **integer number of seconds**; default 2,592,000 (30 days); minimum 86,400 (24 hours); `0` disables; changing it resets the next-report anchor. GET returns the current interval (seconds) and enabled/disabled state.
- **What a "notification sent" is**: a per-recipient delivery that reached at least the `sent` state in 003's `queued → sent → delivered | failed` lifecycle, bucketed by the UTC hour-of-day of the send. Pre-send validation failures (`queued → failed`) and still-`queued` records are excluded.
- **Report delivery**: the report email is sent through a **new dedicated report-email channel** (real SMTP, the seed of a future real email channel) that **reuses the existing resilient delivery pipeline** — retry/backoff + per-destination circuit breaker + idempotency keys + the persisted `queued → sent → delivered | failed` lifecycle — addressed to each account's own email, not to contacts, and not via the transactional verification/reset path. Report sends are **server-originated** (no owning user), so they are excluded from aggregation and from every user's send-history; the rendered graph rides as an **attachment** (the shared message payload gains optional attachment support).
- **Report packaging**: the admin's personal and global reports may be delivered as two separate emails or one email containing both graphs; the exact packaging is a minor plan-level detail. Each graph is a 24-bar image rendered by a Python visual-graphing library and attached or embedded in the email (library choice is a plan-level decision).
- **No recursion**: report emails are **server-originated** sends (no owning user); the per-hour aggregation counts only user-owned sends (`user_id IS NOT NULL`), so reports are excluded from all aggregations and the histogram never inflates.
- **Global scope**: the global aggregate includes every user's sends, the admin's included.
- **Background routing**: the per-hour aggregation runs on the prefork (CPU) pool — the constitution's canonical CPU-bound usage-aggregation task, first exercised by this feature; report email sends run on the threads/I/O pool.
- **Scheduling**: reports are emitted automatically on the configured cadence; there is no on-demand "send now" trigger in this feature.
- **Seeding**: a standalone seeding capability (e.g., a script or one-shot job, as simple as bulk insertion) creates ≈1,000 accounts and ≈500,000 completed sends spread across all 24 hours and many dates, with synthetic account emails, bypassing the live send/resilience pipeline. The constitution's larger "~100,000 events per user" figure is treated as illustrative; ≈500K total governs here.
- **Frontend out of scope**: this feature delivers the backend API surface and behavior only (admin frequency endpoints, scheduled reports, seeding), validated through the API, consistent with 003; a React admin UI is deferred.
- **Builds on 003**: account/auth, the notification send lifecycle (`queued → sent → delivered | failed`), the channel/adapter boundary, and the Celery background-processing model are inherited from the existing foundation, not re-decided here. This feature realizes the CPU-bound usage-aggregation task and the admin-facing notification type that 003 explicitly deferred.
