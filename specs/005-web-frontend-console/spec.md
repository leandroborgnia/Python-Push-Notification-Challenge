# Feature Specification: Enterprise Admin Web Frontend

**Feature Branch**: `005-web-frontend-console`

**Created**: 2026-06-23

**Status**: Draft

**Input**: User description: "Build the complete web frontend for the notification service: one cohesive, professional 'enterprise admin' single-page app in the existing React + Vite `frontend/`, consuming the existing backend API. A single self-contained feature covering authentication (Login, Register, Verify, Request reset, Confirm reset over the OAuth2 password flow + JWT), an app shell with top app bar and tab navigation (Home, Contacts, Templates, Send & History), a client-side per-UTC-hour sending dashboard, contact creation + listing, template CRUD with a contacts recipient picker and channel rules, and template sending + delivery-status history. Clean modern enterprise look using a well-regarded component library and charting library; consistent loading/empty/error states; backend response mapping; client-side validation mirroring backend constraints. No backend changes. Out of scope: stats-report frequency UI, realtime/websocket, i18n, theming/dark-mode, contact edit/delete, admin/role management."

## Clarifications

### Session 2026-06-24

- Q: The dev build serves the SPA at `http://app.localhost` but points it at the API at `http://api.localhost` — a different browser origin — and the backend has no CORS support, so a browser blocks every API call. How should this be resolved given the original "no backend changes" constraint? → A: **Relax the constraint to permit the single minimal cross-origin enablement.** The backend MAY add cross-origin (CORS) support — the chosen mechanism is FastAPI `CORSMiddleware` with allowed origins sourced from `pydantic-settings` — so the browser SPA can call the API. This is the **only** backend change in scope: no business endpoints, schema, or notification/resilience-behavior changes. (Same-origin-via-ingress and ingress-level CORS annotations were the considered alternatives; in-code middleware was chosen for environment portability and testability.)
- Q: The app bar must show the signed-in user, but login returns only an access token and `GET /api/v1/auth/me` returns only a user id (no email). Where does the displayed identity come from? → A: The app shows the **email the user entered at login**, persisted alongside the token; `GET /api/v1/auth/me` is used as a lightweight token-validity probe on load (a 401 there means the stored session is stale).

## User Scenarios & Testing *(mandatory)*

The "system" in this specification is the **web frontend** (a single-page app), plus one minimal,
explicitly-scoped backend change: enabling cross-origin (CORS) requests so a browser SPA on a
different origin can call the API (see Clarifications). Apart from that, the backend's behavior is a
fixed dependency this feature consumes, not something it defines or alters.

### User Story 1 - Authenticate and enter the application (Priority: P1)

Whenever a visitor has no valid session, the app presents a single authentication page as the start
surface. From that one place a person can complete the entire account lifecycle: sign in, register a
new account, verify their email, request a password reset, and confirm a password reset with a new
password. Verification and reset confirmation work both by pasting a token and by clicking an emailed
deep link that carries the token. On a successful sign-in the person lands in the signed-in app shell;
signing out — or any expired/invalid session detected during use — returns them to the auth page.

**Why this priority**: Authentication is the gate for everything else. No tab, table, or chart is
reachable without a session, and the session is what authorizes every other call. It must hold before
any other capability has meaning, and it is independently demonstrable on its own.

**Independent Test**: With no session, confirm the app opens on the auth page defaulting to Login.
Register an account; observe the prompt to verify. Verify via a pasted token and via a `?token=` deep
link (which verifies automatically on load). Log in and land in the app shell showing the signed-in
email; log out and return to the auth page. Request a password reset (always acknowledged), then
confirm it with a token + new password and log in with the new password. Force a 401 (e.g., expired
token) and confirm the app returns to the auth page.

**Acceptance Scenarios**:

1. **Given** no valid session, **When** the app loads, **Then** the authentication page is shown as the start surface, defaulting to the Login mode.
2. **Given** the Login mode, **When** valid credentials for a verified account are submitted, **Then** a session is established and the app routes into the signed-in shell.
3. **Given** the Register mode, **When** an email + password are submitted successfully, **Then** the user is told the account needs email verification and is guided to the Verify step.
4. **Given** an unverified account, **When** the user attempts to log in, **Then** a clear message states verification is required and offers the path to verify.
5. **Given** a verification deep link carrying `?token=...`, **When** the app opens that link, **Then** it attempts verification automatically and reports success or a specific failure (invalid/expired/already used).
6. **Given** the Request-reset mode, **When** any email is submitted, **Then** the app shows an acknowledged/success outcome that does not reveal whether the email is registered.
7. **Given** a reset token (pasted or via `?token=...` deep link) and a new password, **When** Confirm-reset is submitted successfully, **Then** the user is directed to log in with the new password.
8. **Given** a signed-in session, **When** the user logs out, **Then** the session is cleared and the auth page is shown.
9. **Given** a signed-in session, **When** any backend call returns 401 (expired/invalid token), **Then** the session is cleared and the user is returned to the auth page from wherever they were.

---

### User Story 2 - Manage contacts (Priority: P1)

A signed-in user builds their address book on the Contacts tab: a form creates a contact with a
display name and any combination of email, phone, and device token, and a paginated read-only table
lists the user's existing contacts. The backend supports only add and list, so contacts are not
editable or deletable here.

**Why this priority**: Contacts are the recipients that templates point at; without at least one
contact, no template can be addressed and nothing can be sent. It is the first data a user must
create, and it is independently demonstrable.

**Independent Test**: Sign in, open Contacts, submit the create form with a display name and at least
one destination, and confirm the new contact appears in the table without a manual reload. Submit the
form with a display name but no destination and confirm it is blocked with a clear message. Page
through the table when there are more contacts than one page.

**Acceptance Scenarios**:

1. **Given** the Contacts tab, **When** a contact with a display name and at least one destination is submitted, **Then** it is created and appears in the contacts table without a manual reload.
2. **Given** the create-contact form, **When** it is submitted with a display name but no email, phone, or device token, **Then** submission is blocked with a clear "at least one destination required" message.
3. **Given** more contacts than fit one page, **When** the user pages the table, **Then** additional contacts are shown and the table is read-only (no edit/delete/selection).
4. **Given** the user has no contacts yet, **When** the Contacts tab opens, **Then** a helpful empty state is shown rather than an error.

---

### User Story 3 - Manage templates (Priority: P2)

On the Templates tab the user sees a paginated table of their templates; selecting a row enables Edit
and Delete. Creating or editing a template captures a title, content, exactly one channel (Email, SMS,
or Push), and a set of recipients multi-selected from the user's own contacts. The form enforces
channel rules (notably SMS content ≤ 160 characters) and surfaces server validation errors. Deleting
requires an explicit confirmation. Editing or deleting never sends.

**Why this priority**: Templates are the unit that gets sent; they depend on contacts (US2) for
recipients and must exist before the headline send flow (US4). It is independently demonstrable once
contacts exist.

**Independent Test**: With at least one contact present, create a template choosing a channel and
multi-selecting recipients; confirm it appears in the table. Select it, edit the title/content/
recipients, and save. Switch the channel to SMS and confirm content over 160 characters is rejected
with a clear message. Delete a template and confirm the confirmation step is required and that nothing
is sent.

**Acceptance Scenarios**:

1. **Given** at least one contact exists, **When** a template is created with a title, content, one channel, and selected recipient contacts, **Then** it is created and appears in the templates table.
2. **Given** the SMS channel is selected, **When** content exceeds 160 characters, **Then** submission is blocked client-side with a clear message, and any server-side rejection is also surfaced.
3. **Given** a template is selected in the table, **When** Edit is chosen and changes are saved, **Then** the template is updated and the change is reflected without sending anything.
4. **Given** a template is selected, **When** Delete is chosen, **Then** the user must confirm before deletion, and confirming deletes the template without sending it.
5. **Given** the recipient picker, **When** the user opens it, **Then** it offers a multi-select drawn only from the user's own contacts.
6. **Given** a template the backend rejects (e.g., a recipient not owned by the caller), **When** save is attempted, **Then** the server's validation error is surfaced as an actionable message.

---

### User Story 4 - Send a template and track delivery (Priority: P2)

On the Send & History tab the user picks one of their templates and sends it; the app confirms the
send was accepted for background delivery (it does not wait for delivery). A history table lists the
user's past sends with a per-send status, and the user can drill into any send to see each recipient's
delivery state and full lifecycle. Because delivery happens in the background, statuses refresh via a
manual refresh and/or light polling until they reach a terminal state.

**Why this priority**: This is the headline value of a notification service — actually dispatching a
message and observing what happened. It depends on templates (US3) and contacts (US2) being in place.

**Independent Test**: With a valid template, send it and confirm an "accepted for delivery"
acknowledgement appears quickly. Observe the new send in the history table; open it and watch
per-recipient statuses progress (queued → sent → delivered/failed) on refresh or polling. Confirm
server-owned stats-report sends never appear in the history.

**Acceptance Scenarios**:

1. **Given** a valid template is selected, **When** the user sends it, **Then** the app confirms the send was accepted for background delivery without blocking on the outcome.
2. **Given** a template the backend deems unsendable (no recipients / unsupported channel), **When** the user sends it, **Then** a clear error is surfaced and no spurious entry is created.
3. **Given** past sends exist, **When** the Send & History tab opens, **Then** a table lists them with a per-send status.
4. **Given** a send in the table, **When** the user drills into it, **Then** each recipient's delivery state, destination, and lifecycle transitions are shown.
5. **Given** background delivery is in progress, **When** the user refreshes or polling runs, **Then** statuses update toward their terminal state without a full page reload.
6. **Given** the backend excludes server-owned stats-report sends, **When** the history is shown, **Then** those system reports never appear.

---

### User Story 5 - Personal sending dashboard (Priority: P3)

The Home tab is a dashboard of the signed-in user's own sending activity, centered on a 24-bar chart
of their sends per UTC hour — the same per-hour view the stats-report emails visualize — alongside
simple summary statistics. Everything is derived client-side from the user's send history with no
backend change. Because it aggregates over paginated history, it pages until exhausted but caps the
scan at a reasonable maximum; if the cap is hit it indicates the chart reflects a recent window rather
than all-time. A manual refresh re-aggregates after new sends complete.

**Why this priority**: It is valuable insight but strictly derivative of data created by the other
stories; it adds polish and an at-a-glance summary once sending is in place.

**Independent Test**: As a user with sends, open Home and confirm a 24-bar (00–23) chart with
missing hours at zero, plus summary stats (total reached-`sent`, dispatches scanned, most recent send
time). Independently count `sent` transitions over the same history and confirm the bars match. As a
user with no qualifying sends, confirm an all-zero/empty state. With more dispatches than the scan
cap, confirm the "recent window" indication. Trigger a send elsewhere, return and refresh, and confirm
the chart re-aggregates.

**Acceptance Scenarios**:

1. **Given** the user has qualifying sends, **When** Home opens, **Then** a 24-bar chart (UTC hours 00–23, missing hours = 0) of their sends-per-hour is shown with summary statistics.
2. **Given** the user's send history, **When** the per-hour counts are computed, **Then** each bar counts every delivery transition whose resulting status is `sent`, bucketed by the UTC hour of that transition's timestamp (per recipient/delivery, not per dispatch).
3. **Given** the user has no sends that reached `sent`, **When** Home opens, **Then** an all-zero / empty state is shown instead of an error.
4. **Given** the user has more dispatches than the scan cap, **When** aggregation runs, **Then** it stops at the cap and the dashboard indicates the chart reflects a recent window rather than all-time.
5. **Given** new sends completed in the background, **When** the user triggers the manual refresh, **Then** the dashboard re-aggregates and reflects them.

---

### Edge Cases

- **Session expiry mid-action**: a 401 on any call clears the session and returns to the auth page with a message; unsaved form data is lost (acceptable).
- **Bad verification deep link**: an invalid, expired, or already-consumed verification token reports a specific failure with a path to re-request, never a blank screen.
- **Bad reset token**: an invalid/expired reset token on Confirm-reset reports a specific failure with a path to request a new reset.
- **Duplicate registration**: registering an already-registered email surfaces "email already registered" (409) rather than a generic error.
- **Unsendable template**: sending a template the backend rejects (no recipients / unsupported channel) surfaces a 400 message and creates no spurious history entry.
- **Stale template**: editing or deleting a template that no longer exists/owned surfaces "not found" (404) cleanly.
- **Contact without destination**: blocked client-side; if it reaches the server, the 422 is surfaced.
- **Large recipient list**: the recipient picker remains usable (searchable/scrollable) with many contacts.
- **Very large send history**: the dashboard hits its scan cap and shows the "recent window" indicator; the history table itself pages without trying to load everything at once.
- **Empty states everywhere**: no contacts, no templates, no sends each show a helpful empty state, not an error.
- **Network / server error**: a connection failure or 5xx on any call shows an error state plus a non-blocking toast, with retry where applicable.
- **Slow background delivery**: deliveries remain at `queued`/`sent` and advance on poll/refresh as they progress; the UI never appears stuck.

## Requirements *(mandatory)*

### Functional Requirements

**Application shell & navigation**

- **FR-001**: When no valid session exists, the app MUST present the authentication page as the start surface; when a valid session exists, it MUST route into the signed-in app shell.
- **FR-002**: The signed-in shell MUST show a persistent top app bar with the product name, the signed-in user's identity (email), and a logout action.
- **FR-003**: The shell MUST provide primary tab navigation across Home, Contacts, Templates, and Send & History, with the active tab clearly indicated.
- **FR-004**: Logout MUST clear the client-side session and return the user to the authentication page.
- **FR-005**: Any backend response indicating an invalid/expired/missing session (401) MUST clear the session and return the user to the authentication page, regardless of the current screen.

**Authentication & account lifecycle**

- **FR-006**: The authentication page MUST default to Login and allow switching, in one place, between Login, Register, Verify email, Request password reset, and Confirm password reset.
- **FR-007**: Login MUST accept email + password and, on success, establish a session by retaining the issued access token and attaching it as a bearer credential on every subsequent authenticated request.
- **FR-008**: Register MUST accept email + password and, on success, inform the user that the account needs email verification and guide them to the Verify step.
- **FR-009**: Verify MUST accept a pasted verification token and confirm the account, and MUST also accept a token delivered via a deep link and attempt verification automatically on load, reporting success or a specific failure.
- **FR-010**: Request password reset MUST accept an email and always present an acknowledged/success outcome that does not reveal whether the email is registered.
- **FR-011**: Confirm password reset MUST accept a reset token (pasted or via deep link) plus a new password and, on success, direct the user to log in with the new password.
- **FR-012**: A login attempt on an unverified account MUST surface a clear message that verification is required and offer the path to verify.
- **FR-013**: Password fields (Register, Confirm reset) MUST enforce the backend minimum length (8 characters) before submission.

**Contacts**

- **FR-014**: Users MUST be able to create a contact with a display name and optionally any combination of email, phone, and device token.
- **FR-015**: The contact form MUST require at least one destination (email, phone, or device token) in addition to the display name, mirroring the backend rule, and MUST surface the server's rejection if it occurs.
- **FR-016**: Users MUST see their contacts in a paginated, read-only table; contacts MUST NOT be editable or deletable (no row selection or row actions).
- **FR-017**: On successful contact creation, the contacts table MUST reflect the new contact without requiring a manual page reload.

**Templates**

- **FR-018**: Users MUST see their templates in a paginated table that supports selecting a row to enable Edit and Delete actions.
- **FR-019**: Users MUST be able to create a template with a title, content, exactly one channel (Email, SMS, or Push), and a set of recipients chosen by multi-selecting from their own contacts.
- **FR-020**: The template form MUST enforce channel-specific constraints client-side — at minimum SMS content ≤ 160 characters — and MUST surface the backend's validation errors (content/channel/recipients) when the server rejects a submission.
- **FR-021**: Users MUST be able to edit an existing template's title, content, channel, and recipients and save the changes.
- **FR-022**: Users MUST be able to delete a template only after an explicit confirmation step.
- **FR-023**: Creating, editing, or deleting a template MUST never send the template.

**Send & history**

- **FR-024**: Users MUST be able to select one of their templates and send it, and the app MUST confirm the send was accepted for background delivery without blocking on the delivery outcome.
- **FR-025**: Users MUST see a history table of their past sends, each with a per-send status.
- **FR-026**: Users MUST be able to drill into a send to view each recipient's delivery state, destination, optional failure reason, and lifecycle transitions.
- **FR-027**: The send history and any open send detail MUST update as background delivery progresses — via a manual refresh and/or light automatic polling — until deliveries reach a terminal state.
- **FR-028**: Server-owned stats-report sends MUST NOT appear in the history; the app MUST rely on the backend's existing exclusion and MUST NOT request their inclusion.

**Home dashboard**

- **FR-029**: The Home dashboard MUST present the signed-in user's own sending activity centered on a 24-bar chart of their sends per UTC hour (00–23), with missing hours shown as zero.
- **FR-030**: The per-hour counts MUST be derived client-side from the user's send history by counting every delivery lifecycle transition whose resulting status is `sent`, bucketed by the UTC hour of that transition's timestamp, counted per recipient/delivery (not per dispatch) — matching the backend's emailed-graph definition.
- **FR-031**: The dashboard MUST show summary statistics alongside the chart, including at least the total number of deliveries that reached `sent`, the total number of dispatches scanned, and the most recent send time.
- **FR-032**: When the user has no sends that reached `sent`, the dashboard MUST show an all-zero / empty state rather than an error.
- **FR-033**: Aggregation MUST page through the user's send history until exhausted but MUST cap the scan at a defined maximum number of dispatches; if the cap is reached, the dashboard MUST indicate that the chart reflects a recent window rather than all-time.
- **FR-034**: The dashboard MUST provide a manual refresh that re-aggregates so newly completed sends are reflected.

**Cross-cutting**

- **FR-035**: Every data view and action MUST present consistent loading, empty, and error states (no blank or stuck screens).
- **FR-036**: Backend error responses (400, 401, 403, 404, 409, 422) MUST be mapped to clear, actionable messages, and success/error outcomes for user actions MUST be communicated via non-blocking toast notifications.
- **FR-037**: Client-side validation (email format, SMS length, required fields, password length) MUST mirror backend constraints, with the server treated as the source of truth — any server rejection MUST always be surfaced even if client validation passed.
- **FR-038**: The interface MUST be responsive across common desktop and tablet widths and meet reasonable accessibility expectations (keyboard navigability, labeled form fields, sufficient color contrast).
- **FR-039**: Lists the backend paginates (contacts, templates, sends) MUST be retrieved using the backend's `limit` (≤ 100) + `offset` paging; tables MAY additionally paginate client-side over retrieved data.
- **FR-040**: The app MUST consume the existing backend API for all business behavior and MUST NOT depend on any new or modified business endpoint, schema, or change to notification/resilience behavior. The **only** permitted backend change is the minimal cross-origin enablement (CORS) required for the browser SPA (origin `http://app.localhost`) to call the API (origin `http://api.localhost`); allowed origins MUST be configuration-driven, never hard-coded.

### Key Entities *(include if feature involves data)*

- **Session**: the signed-in state, represented by an access token retained client-side and the associated user email; established by login and ended by logout or any 401. There is no refresh-token flow.
- **Contact**: a recipient the user owns — a display name plus at least one destination (email, phone, and/or device token). Created and listed only; not editable or deletable.
- **Template**: a reusable message the user owns — a title, content, exactly one channel (Email/SMS/Push), and a set of recipient contacts. Created, edited, and deleted; sending is a separate action.
- **Send (Dispatch)**: one act of sending a template — a channel, a creation time, and a set of per-recipient deliveries. Listed in history and drillable.
- **Delivery**: a single recipient's outcome within a send — a current status (`queued`/`sent`/`delivered`/`failed`), a destination, an optional failure reason, and an append-only list of lifecycle transitions (from-status, to-status, reason, attempt, timestamp).
- **Per-hour send aggregate**: a client-computed set of 24 counts (one per UTC hour) of deliveries that reached `sent`, plus summary statistics; derived from the send history, not stored.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% routing correctness for session state — an unauthenticated visitor always lands on the authentication page, and a signed-in user always lands in the app shell.
- **SC-002**: A new user can go from registration through verification to a signed-in session using only the in-app auth flows plus the emailed token, without leaving the app's authentication surface.
- **SC-003**: A user can complete the create-contact → create-template → send → observe-delivery path entirely in the UI, and the send's per-recipient statuses visibly progress to a terminal state without a manual page reload.
- **SC-004**: 100% of backend validation failures (e.g., SMS over 160 characters, missing destination, duplicate email registration, recipient not owned) are surfaced as a specific, actionable message rather than a generic failure or silent no-op.
- **SC-005**: Any session expiry (401) during use returns the user to the authentication page without a crash or stuck screen, and re-login restores access.
- **SC-006**: The Home chart's 24 per-hour counts equal an independent count of `sent` transitions over the same scanned history, and a user with no qualifying sends sees the empty state instead of an error.
- **SC-007**: Clicking an emailed verification or reset link opens the app directly in the corresponding step; verification completes automatically with no manual token entry required.
- **SC-008**: Every primary screen presents a distinct loading, empty, and error state — verifiable by exercising each condition — with no blank screens.
- **SC-009**: When the dashboard's scan cap is reached, it indicates the chart reflects only a recent window rather than all-time, so the figure is never silently misleading.
- **SC-010**: After triggering a send, the user receives an acceptance confirmation within 2 seconds under normal conditions; the app never blocks waiting for delivery to complete.

## Assumptions

- **Backend behavior is fixed, with one infrastructure exception**: this feature consumes the existing endpoints exactly as they behave today — auth (`register`, `verify`, `login` via OAuth2 password flow, `me`, `reset-request`, `reset-confirm`), contacts (add + list only), templates (list/create/update/delete/send), and sends (list + detail). The **only** backend modification in scope is enabling cross-origin (CORS) requests so the browser SPA can call the API (see Clarifications); no business endpoint, schema, or notification/resilience-behavior change is in scope. Foreign-resource access returning 404 (not 403) is an existing backend behavior the app treats as "not found / not available."
- **Signed-in identity**: `GET /api/v1/auth/me` returns only the user id (no email), so the app bar displays the email the user entered at login, persisted alongside the access token; `/me` doubles as a token-validity probe when a stored session is restored on load.
- **Existing app & URLs**: the frontend already exists as a React + Vite app served at `http://app.localhost`; the API base URL is provided via `VITE_API_BASE_URL` (defaulting to `http://api.localhost` in dev). These are environment facts, not new decisions.
- **Session persistence**: the access token is retained client-side so the session survives a page reload; there is no refresh-token flow, so when the token expires the next 401 ends the session and returns to login. The exact storage mechanism and any XSS hardening are plan-level decisions.
- **Dashboard "sent" definition**: matches the backend's emailed-graph definition — count each per-recipient delivery transition whose `to_status` is `sent`, bucketed by the UTC hour of that transition's `at` timestamp (per delivery, not per dispatch).
- **Dashboard scan cap**: aggregation pages the send history in pages of up to 100 and stops at a maximum on the order of ~2,000 dispatches (≈20 pages); reaching the cap triggers the "recent window" indicator. The exact cap is a plan-level tunable.
- **History freshness**: send statuses refresh via manual refresh plus light polling (e.g., every few seconds) while any visible delivery is non-terminal, stopping once all are terminal. The exact cadence is a plan-level decision.
- **Client-side table pagination**: contacts/templates/sends tables use sensible default page sizes (e.g., 10–25 rows) over data retrieved with the backend's limit/offset paging.
- **Deep-link routing**: verification and reset-confirm deep links map to distinct in-app routes/modes so the app knows which token flow to run; the backend's emailed links target those routes.
- **Library choices**: a well-regarded enterprise React component library (e.g., Ant Design; MUI or Mantine acceptable) and a charting library (e.g., Recharts or `@ant-design/plots`) are used instead of hand-rolled components; the exact choice is a plan-level decision consistent with the preference for established libraries.

## Out of Scope

- The admin stats-report frequency configuration UI (the `/admin/*` surface from feature 004).
- Real-time / websocket updates (status freshness is via manual refresh + light polling only).
- Internationalization / localization.
- Theming / dark-mode switching.
- Contact editing or deletion (unsupported by the backend — add + list only).
- Any admin / role management or promote/demote UI.
- Any change to the existing notification/resilience behavior or business API contracts. (The **sole** permitted backend change is CORS enablement; see Clarifications.)
