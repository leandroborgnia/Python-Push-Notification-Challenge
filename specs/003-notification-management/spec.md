# Feature Specification: Notification Template Management & Multi-Channel Sending

**Feature Branch**: `003-notification-management`

**Created**: 2026-06-21

**Status**: Draft

**Input**: User description: "Basic notification management system for authenticated users: registration/login with access tokens, per-user notification management, and sending through Email / SMS / Push channels with channel-specific logic that is open for extension." Clarified (Session 2026-06-21): *notification management* is **template** management (create/modify/delete/list templates that never send by themselves); **sending** is a separate, repeatable action; recipients come from a per-user **contacts book** and are stored on the template; sending attempts every recipient independently and tolerates individual failures.

## Clarifications

### Session 2026-06-21

- Q: When a template is sent, does the dispatch capture a snapshot of the template's content/channel/recipients, or reference the live (editable) template? → A: A standalone snapshot taken at send time — the dispatch stores its own copy and holds **no association** to the template entity (no reference back), even while the template still exists unchanged; later edits or deletion of the template never affect prior sends.
- Q: When SMS content exceeds 160 characters, is it rejected at template save, truncated at send, or failed at send? → A: Rejected at template save — creating or modifying an SMS template with content over 160 characters fails validation, so every SMS send is guaranteed ≤160 characters (no truncation, no send-time length failure).
- Q: Email verification and password-reset emails must reach the user, but the notification channels are simulated — how are these auth emails delivered? → A: Auth verification/reset emails are **not** notifications. They are delivered through a separate, simple, **direct** path that performs **real** email delivery, independent of the notification channels and the Celery dispatch/resilience pipeline. The three notification channels are explicitly **simulated** implementations — named `simulatedEmail` / `simulatedSMS` / `simulatedPush` — built for testing purposes, not final channel integrations.
- Q: How is the `sent → delivered | failed` confirmation obtained for each simulated channel? → A: `sent` is recorded when the simulated channel **accepts** the outbound send; the final `delivered | failed` outcome then arrives **asynchronously** and is **channel-specific**. **simulatedSMS** exposes a status endpoint the system must **poll** (a background poll) to learn the outcome. **simulatedEmail** and **simulatedPush** instead **call back an inbound webhook endpoint** the system exposes, reporting the outcome automatically — the webhook is assumed **pre-configured**, so only the receiving endpoints are built (no registration step). In every case the reported outcome drives the appended `delivered | failed` transition.
- Q: Does this feature deliver a React frontend UI, or is it backend-API-only? → A: Backend API surface and behavior only — all user stories are delivered and validated **through the API** per the Independent Tests. A React frontend UI is **out of scope** for `003` and deferred to a later feature; the constitution's project-level React app remains a future deliverable, not part of this feature.
- Q: A recipient lacking the channel's destination/valid format has no `skipped` state in the lifecycle — how is it represented? → A: As a terminal **`failed`** outcome carrying a **reason** (e.g., `missing_destination`, `invalid_format`, `invalid_device_token`). The record transitions `queued → failed` **directly**, without ever reaching `sent` (nothing was handed to the channel); no `skipped` state is added. The reason distinguishes a pre-send validation failure from a channel-delivery failure. The spec's earlier "skipped/failed" wording is normalized to this single `failed`-with-reason model.
- Q: Is the constitution's CPU-bound usage-aggregation (per-UTC-hour bar graph, prefork pool) in scope for this feature? → A: No. For `003`, all background work is assumed **I/O-bound** (channel sends and delivery-confirmation polling), routed to the threads/I/O pool; the prefork (CPU) pool is **not exercised** here. The CPU-bound usage-aggregation task is **deferred to a later spec**, where it will support a future **admin-facing notification type**.
- Q: How are the inbound delivery-confirmation webhook endpoints (and outbound sends to the simulated channels) secured? → A: They require **no authentication**. This app's user authentication (user → our API) is separate from the simulated providers, whose auth is **not simulated** (there is no provider token). Sending to the simulated channels needs no credentials, and the provider's webhook callback to our endpoints needs none either — it is **machine-to-machine**. (A real implementation would use a server certificate or API key; for this simulation it is unauthenticated.) The webhook endpoints are **exempt from FR-006's user-token requirement**; integrity relies on correlating each callback to a known delivery (uncorrelated/duplicate callbacks are ignored, per FR-031). No **sender identity** (sender email or sender phone) is required for any of the three channels.
- Q: Is there a bound on how long a delivery can wait in `sent` for confirmation? → A: **No confirmation deadline** — a delivery may remain `sent` **indefinitely**. There is only a **polling deadline**: for SMS, the background poll runs for a bounded window sized to normal SMS delivery speed; if no terminal outcome is reported by then, the system **stops polling** and leaves the delivery in `sent` (assumed sent — it is **never** auto-changed to `failed`). Email/Push are purely webhook-driven, so if no callback ever arrives the delivery likewise stays `sent` indefinitely. Only an actually-reported outcome moves a delivery to `delivered`/`failed`. Exact timings are a plan-level detail (assume normal SMS speed for the poll window).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Secure account access (Priority: P1)

A person registers with their email and a password, confirms ownership of that email, then logs in to receive an access token they present on every subsequent request. Without a valid token, none of the notification, sending, or contacts capabilities are reachable, and one user can never act on another user's data.

**Why this priority**: Identity and ownership gate every other capability in the system. It is the security foundation, and it is independently demonstrable on its own.

**Independent Test**: Register a new account, complete email verification, log in to obtain a token, call a protected endpoint successfully with the token, and confirm the same endpoint is rejected without (or with an invalid) token.

**Acceptance Scenarios**:

1. **Given** no existing account for an email, **When** the person registers with that email and a password, **Then** an unverified account is created and a verification step is initiated.
2. **Given** an unverified account, **When** the person attempts to log in, **Then** access is refused until the email is verified.
3. **Given** a verified account, **When** the person logs in with correct credentials, **Then** they receive a valid access token.
4. **Given** a valid access token, **When** the person calls any notification/contact endpoint, **Then** the request is authorized; **When** the token is missing, expired, or invalid, **Then** the request is rejected as unauthenticated.
5. **Given** a person who has forgotten their password, **When** they request a reset and complete the reset flow, **Then** they can log in with the new password and the old password no longer works.

---

### User Story 2 - Manage notification templates (Priority: P1)

An authenticated user creates reusable notification templates — each with a title, content, a single channel (Email, SMS, or Push), and a set of their own contacts as recipients. They can modify, delete, and list their own templates. Creating or editing a template **never sends anything**; templates are definitions, ready to be sent later.

**Why this priority**: This is the core "notification management" surface — the durable thing users curate and reuse. It delivers standalone value (a managed library of templates) even before sending exists.

**Independent Test**: As an authenticated user, create a template referencing one or more of your contacts, list it back, modify its content, list it again to see the change, delete it, and confirm it no longer appears — with no send occurring at any point.

**Acceptance Scenarios**:

1. **Given** an authenticated user with at least one contact, **When** they create a template with a title, content, channel, and recipient contacts, **Then** the template is stored and no send is triggered.
2. **Given** a user's own template, **When** they modify its title/content/channel/recipients, **Then** the changes are saved and still no send occurs.
3. **Given** a user's own template, **When** they delete it, **Then** it is removed from their template list.
4. **Given** an authenticated user, **When** they list templates, **Then** they see only their own templates and never another user's.
5. **Given** a template that references contacts, **When** any referenced contact is not owned by the user, **Then** the create/modify is rejected.

---

### User Story 3 - Send a notification across its channel (Priority: P1)

An authenticated user sends one of their valid templates. The system immediately acknowledges that the notification was accepted and is being sent, then dispatches it in the background to each recipient contact through the template's channel, applying channel-specific logic. Each recipient is handled independently and resiliently, every delivery's outcome is tracked, and the same template can be sent again any number of times.

**Why this priority**: This is the headline capability and the project's core learning goal — resilient, asynchronous, channel-specific dispatch. It is what turns a template library into a working notification service.

**Independent Test**: Send a valid template, confirm an immediate "accepted/sending" acknowledgement (without waiting for delivery), then observe that each recipient progresses through its own lifecycle to a final outcome; send the same template a second time and confirm it is tracked as a separate dispatch.

**Acceptance Scenarios**:

1. **Given** a valid template, **When** the user sends it, **Then** the system responds immediately that the notification was accepted and is being sent (it does not wait for delivery to complete).
2. **Given** an accepted send, **When** delivery runs in the background, **Then** each recipient is dispatched through the template's channel and its lifecycle is recorded as `queued → sent → delivered | failed`.
3. **Given** a recipient contact that lacks the channel's destination (e.g., an SMS channel but no phone number), **When** the send runs, **Then** that recipient is recorded as `failed` with a reason (transitioning `queued → failed` without ever reaching `sent`) while the remaining recipients still send.
4. **Given** a channel experiencing simulated latency, errors, rate-limits, or timeouts, **When** delivery is attempted, **Then** it retries with backoff, a circuit breaker guards repeated failures, and no recipient receives a duplicate delivery for that send.
5. **Given** a template already sent once, **When** the user sends it again, **Then** a new, independent dispatch is created and tracked separately (re-sends are not deduplicated against earlier sends).
6. **Given** a template that is not valid to send (no supported channel, or no recipient contacts), **When** the user attempts to send it, **Then** the send is rejected with a clear, actionable error.
7. **Given** the user's own dispatches, **When** they query a template's send activity, **Then** they can see each recipient's outcome and status transitions.

---

### User Story 4 - Manage a personal contacts book (Priority: P2)

An authenticated user adds contacts (a name plus the destinations they own: email, phone number, and/or device token) and lists their own contacts so they can reference them as recipients on templates. Contacts are private to the user who added them.

**Why this priority**: Contacts are the recipient source that templates and sending depend on, but the surface is intentionally small (add + list). It supports the P1 stories rather than standing alone as the headline.

**Independent Test**: As an authenticated user, add a contact, list contacts and see it, and confirm another user cannot see or use it.

**Acceptance Scenarios**:

1. **Given** an authenticated user, **When** they add a contact with a name and one or more destinations, **Then** the contact is stored and associated with that user.
2. **Given** an authenticated user with contacts, **When** they list their contacts, **Then** they see all and only their own contacts.
3. **Given** a contact owned by user A, **When** user B attempts to view or use it, **Then** the request is denied.

---

### Edge Cases

- **Duplicate registration**: registering an email that already has an account is rejected.
- **Unverified access**: an unverified account cannot obtain a token or reach protected endpoints until verification completes.
- **Expired/invalid token**: any protected request with a missing, malformed, or expired token is rejected as unauthenticated.
- **Cross-user access**: reading, modifying, deleting, or sending another user's template — or referencing another user's contact — is denied.
- **Empty recipient set**: a template with no recipient contacts is not valid to send and is rejected at send time.
- **Missing channel destination**: a recipient without the channel's destination (e.g., SMS with no phone) is recorded as a terminal `failed` with a reason (e.g., `missing_destination`), transitioning `queued → failed` without ever reaching `sent`; the remaining recipients still send (the batch never aborts on individual failures).
- **Over-length SMS**: an SMS template whose content exceeds 160 characters is rejected at create/modify time, so over-length SMS content never reaches the send step.
- **Channel failure modes**: simulated latency, random errors, rate-limits (e.g., "too many requests"), and timeouts are absorbed by retry-with-backoff and a per-channel/destination circuit breaker; idempotency prevents duplicate delivery on retry.
- **Asynchronous confirmation**: a delivery stays in `sent` until its channel reports an outcome (polled status for SMS; webhook callback for Email/Push). Duplicate or repeated confirmations for the same delivery are handled idempotently and never overwrite an already-recorded final outcome; a confirmation that cannot be correlated to a known delivery is rejected/ignored without corrupting state.
- **Confirmation never arrives**: there is no confirmation deadline — a delivery may remain `sent` indefinitely. SMS polling has only a bounded poll window (normal SMS speed); when it elapses the system stops polling and leaves the record `sent` (assumed sent, never auto-failed). Email/Push remain `sent` until a webhook callback (if any) arrives.
- **Repeated sends**: sending the same template multiple times produces multiple independent dispatches, each tracked separately.
- **Template deleted after sending**: prior dispatch/delivery history is unaffected — each dispatch is a standalone snapshot with no link back to the template, so modifying or deleting the template never changes past sends.

## Requirements *(mandatory)*

### Functional Requirements

**Authentication & authorization**

- **FR-001**: System MUST let a person register an account with an email and a password; the email MUST be unique across accounts.
- **FR-002**: System MUST store passwords securely such that the original password cannot be recovered from storage.
- **FR-003**: System MUST require email verification before a newly registered account can obtain an access token. The verification email MUST be delivered through a separate, direct transactional-email path that performs **real** delivery — it is **not** a notification and MUST NOT use the simulated notification channels or the background dispatch/resilience pipeline.
- **FR-004**: System MUST issue an access token in response to a successful login with valid credentials on a verified account.
- **FR-005**: System MUST provide a password-reset flow (request a reset, then set a new password via the emailed reset), after which the previous password is invalid. The reset email MUST be delivered through the same separate, direct transactional-email path as verification (real delivery, distinct from the simulated notification channels).
- **FR-006**: System MUST require a valid access token on every contact, template, and sending endpoint, and MUST reject missing/invalid/expired tokens as unauthenticated. The inbound delivery-confirmation webhook endpoints (FR-031) are **machine-to-machine** and are **exempt** from this user-token requirement — in this simulation they are unauthenticated (a real deployment would secure them with a server certificate or API key); their integrity relies on correlating each callback to a known delivery (FR-031).
- **FR-007**: System MUST enforce ownership: a user MUST only be able to read, modify, delete, or send their own templates, and MUST only be able to reference and use their own contacts; access to another user's resources MUST be denied.

**Contacts**

- **FR-008**: System MUST let an authenticated user add a contact consisting of a display name and one or more destinations (email address, phone number, and/or device token), associated with that user.
- **FR-009**: System MUST let an authenticated user list all of their own contacts.
- **FR-010**: System MUST keep contacts private to the owning user (no cross-user visibility or use).

**Notification templates**

- **FR-011**: System MUST let an authenticated user create a notification template with a title, content, a single channel, and a set of recipient contacts drawn from the user's own contacts.
- **FR-012**: System MUST let a user modify their own template (title, content, channel, recipients).
- **FR-013**: System MUST let a user delete their own template.
- **FR-014**: System MUST let a user list their own templates.
- **FR-015**: System MUST store the recipient contacts on the template; a template MAY reference one or more contacts, and every send targets the template's stored recipient set.
- **FR-016**: System MUST support the channels **Email**, **SMS**, and **Push**. These are **simulated** channel implementations (named `simulatedEmail` / `simulatedSMS` / `simulatedPush`) intended for testing — they emit/log the send and inject failure modes rather than integrating a production provider; they are distinct from the real, direct auth-email path of FR-003/FR-005.
- **FR-017**: Creating or modifying a template MUST NOT trigger any send.
- **FR-018**: System MUST validate channel-specific content constraints when a template is created or modified, and specifically MUST reject creating or modifying an **SMS** template whose content exceeds 160 characters (so SMS content never needs truncation or send-time length handling).

**Sending**

- **FR-019**: System MUST let a user send a valid template, and MUST allow the same template to be sent any number of times.
- **FR-020**: A send request MUST be acknowledged immediately as "accepted / being sent" without waiting for channel delivery to complete.
- **FR-021**: Actual channel delivery MUST occur asynchronously in the background, separate from the send request.
- **FR-022**: For a send, the system MUST attempt every recipient contact independently; it MUST NOT abort the batch on an individual failure, and recipients lacking the channel's destination (or failing channel validation) MUST be recorded as a terminal `failed` with a reason — transitioning `queued → failed` directly, without ever reaching `sent` — while the remaining recipients proceed.
- **FR-023**: Each channel MUST apply its own send logic, including at minimum:
  - **Email** (`simulatedEmail`): validate the recipient's email format, generate the message from the template, and log the send; the `delivered | failed` outcome later arrives via an inbound webhook callback (FR-031).
  - **SMS** (`simulatedSMS`): content is already constrained to 160 characters at template save (FR-018); the send logs the recipient number and send date; the `delivered | failed` outcome is obtained by polling the provider's status endpoint (FR-031).
  - **Push** (`simulatedPush`): validate the device token, format the payload, and log the send status; the `delivered | failed` outcome later arrives via an inbound webhook callback (FR-031).
- **FR-024**: Every outbound delivery MUST be protected by retry with exponential backoff, a circuit breaker per channel/destination, and idempotency that prevents duplicate delivery on retry.
- **FR-025**: System MUST model and persist each recipient's send lifecycle as append-only history with the states `queued → sent → delivered | failed`; transitions MUST never be silently overwritten. A pre-send validation failure (missing destination, invalid format, invalid device token) MUST transition `queued → failed` directly without reaching `sent`; every `failed` transition MUST capture a reason. No separate `skipped` state exists.
- **FR-026**: Repeated user-initiated sends of the same template MUST be treated as distinct dispatches; idempotency MUST apply only within a single send's retries, not across separate sends.
- **FR-027**: System MUST let a user view the status and per-recipient outcomes of their own sends.
- **FR-028**: Adding a new channel MUST require only introducing a new channel implementation, with **zero** changes to existing channel logic or the shared dispatch flow.
- **FR-029**: System MUST reject an attempt to send an invalid template (no supported channel, or no recipient contacts) with a clear, actionable error.
- **FR-030**: When a template is sent, the system MUST capture a standalone snapshot of its title, content, channel, and recipients at send time; the resulting dispatch MUST NOT be associated with the template entity, so subsequent edits or deletion of the template never alter any past send.
- **FR-031**: The `sent → delivered | failed` transition MUST be driven by an asynchronous, channel-specific delivery-confirmation mechanism:
  - **simulatedSMS**: the system MUST poll the provider's delivery-status endpoint (a background poll) and record the reported outcome as the `delivered | failed` transition. The poll runs for a bounded window sized to normal SMS delivery speed (exact timing is a plan-level detail); if the window elapses with no terminal outcome, the system MUST stop polling and leave the delivery in `sent` (assumed sent — it MUST NOT be auto-changed to `failed`).
  - **simulatedEmail** and **simulatedPush**: the system MUST expose inbound webhook endpoint(s) that the provider calls back automatically to report the outcome, and record it as the `delivered | failed` transition. Webhook delivery is assumed **pre-configured** by the provider — only the receiving endpoints are built; the system performs no webhook registration step. These endpoints are **unauthenticated** machine-to-machine callbacks (exempt from FR-006, see that requirement).
  - Outbound sends to the simulated channels require **no provider credentials**, and the simulated channels require **no sender identity** (no sender email or sender phone) for any of the three channels.
  - A delivery record stays in `sent` until its channel's confirmation reports an outcome; the inbound webhook/poll handling MUST correlate the confirmation to the correct delivery record and append the transition (never overwrite, per FR-025), tolerating duplicate/again-delivered confirmations idempotently, and ignoring confirmations that cannot be correlated to a known delivery. There is **no confirmation deadline**: absent a reported outcome a delivery MAY remain `sent` indefinitely. Only the SMS poll has a deadline, and reaching it merely stops polling — it never changes the status.

### Key Entities *(include if feature involves data)*

- **User account**: a registered person. Key attributes: unique email, securely stored password, verification status. Owns contacts and templates.
- **Contact**: a recipient in a user's private contacts book. Key attributes: owner (user), display name, optional email / phone number / device token. Reusable across that user's templates; never visible to other users.
- **Notification template**: a reusable notification definition owned by a user. Key attributes: owner, title, content, channel (Email/SMS/Push), recipient contacts. Freely editable; never sends on its own.
- **Send (dispatch)**: a single user-initiated act of sending. Key attributes: a **standalone snapshot** of the title, content, channel, and recipient set captured at send time; the initiating user; the time of send. The dispatch holds **no association to the template entity** — it is a self-contained copy, so later edits or deletion of the template never alter it. Repeatable — each send is independent.
- **Delivery (per-recipient send record)**: the attempt to deliver one dispatch to one recipient contact via the channel. Key attributes: dispatch, recipient contact, channel, current lifecycle status (`queued → sent → delivered | failed`), append-only transition history, a failure reason set on any `failed` outcome (distinguishing pre-send validation failures such as `missing_destination` from channel-delivery failures), and a provider/correlation reference used to match the asynchronous delivery confirmation (polled status for `simulatedSMS`; webhook callback for `simulatedEmail` / `simulatedPush`) back to this record.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A brand-new user can go from registration through email verification and login to creating their first contact and template in under 5 minutes, without assistance.
- **SC-002**: 100% of contact, template, and sending requests made without a valid token are rejected.
- **SC-003**: In testing, a user can never read, modify, delete, or send another user's templates, nor reference another user's contacts (zero cross-user access).
- **SC-004**: A send request returns an "accepted / being sent" acknowledgement in under 1 second, regardless of the number of recipients or channel latency.
- **SC-005**: The same template can be sent repeatedly, and each send is recorded and observable as a separate dispatch with its own per-recipient outcomes.
- **SC-006**: For every send, each recipient's lifecycle transitions (`queued → sent → delivered | failed`) are individually observable after the fact.
- **SC-007**: Under simulated channel failures (latency, random errors, rate-limits, timeouts), no recipient receives a duplicate delivery for a single send, and transient failures recover without manual intervention.
- **SC-008**: A new channel can be added by introducing one new channel implementation with no edits to any existing channel's logic or the shared dispatch flow (verifiable by inspection and tests).
- **SC-009**: Channel-specific rules are observably enforced: SMS sends never exceed 160 characters, email sends validate recipient format, and push sends validate the device token before dispatch.

## Assumptions

- **Recipients are stored on the template** (chosen at create/modify time); every send targets the template's current recipient set rather than a per-send selection.
- **Contacts support add + list only** in this version (no modify or delete endpoint); each contact holds an optional email, phone number, and/or device token, and the channel-relevant destination is used at send time.
- **Email verification gates access**: an unverified account cannot obtain an access token or reach protected endpoints until verification completes.
- **Access token only** (no refresh tokens in this version); when a token expires the user logs in again. A standard, finite token lifetime applies. A password reset invalidates the password but does **not** revoke already-issued access tokens — they simply expire at their normal (short) lifetime (no server-side revocation list this version).
- **Per-recipient independent delivery**: the system does not pre-validate recipients against the channel before sending; it attempts each one and tolerates individual failures (missing destination, invalid format) without aborting the batch.
- **Repeated sends are intentional and distinct**; idempotency is scoped to a single send's retry attempts, never across separate user-initiated sends.
- **Send history is durable and decoupled**: each dispatch is a standalone snapshot captured at send time and holds no reference to the template, so it is retained and unchanged even if the template is later modified or deleted.
- **Channel set is Email/SMS/Push for this version**, with the explicit expectation that more channels can be added later without touching existing channel logic.
- **Notification channels are simulated**: the Email/SMS/Push channel adapters are deliberately simulated implementations (`simulatedEmail` / `simulatedSMS` / `simulatedPush`) that log/emit the send and inject failure modes for testing; they are not production provider integrations.
- **Delivery confirmation is asynchronous and channel-specific**: `simulatedSMS` is **polled** for its delivery outcome; `simulatedEmail` and `simulatedPush` **call back** inbound webhook endpoints the system exposes. Webhook delivery is assumed already configured by the provider — the system only implements the receiving endpoints (no registration step) — and the simulated providers invoke those endpoints automatically.
- **Auth emails use a separate direct path**: email verification and password-reset messages are transactional auth events, not notifications. They are delivered through a separate, simple, direct path that performs real delivery and does not pass through the simulated notification channels or the background dispatch/resilience pipeline.
- **Simulated providers are unauthenticated and identity-less**: this app's user authentication is independent of the simulated channels. Sending to the channels needs no credentials, the providers' inbound webhook callbacks need no authentication (machine-to-machine; a real deployment would use a server certificate or API key), and no sender identity (sender email or sender phone) is required for any of the three channels.
- **Email message generation** is a straightforward templated body for this version (no rich/visual template editor).
- **Frontend is out of scope for this feature**: `003` delivers the backend API (auth, contacts, templates, sending, async delivery/confirmation, status queries) validated through the API; the constitution's React frontend is deferred to a later feature.
- **CPU-bound work is out of scope**: this feature's background processing is entirely **I/O-bound** (channel sends + delivery-confirmation polling) on the threads/I/O pool; the prefork (CPU) pool is not exercised here. The constitution's CPU-bound usage-aggregation task (per-UTC-hour bar graph, prefork pool) is deferred to a later spec that introduces an admin-facing notification type.
- This feature **builds on the existing notification-service foundation** (hexagonal architecture, background processing, persisted resilience lifecycle, OAuth2/token auth, secure password hashing) defined by the project constitution; those technology choices are inherited, not re-decided here.
