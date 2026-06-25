---
description: "Task list for Enterprise Admin Web Frontend (005-web-frontend-console)"
---

# Tasks: Enterprise Admin Web Frontend

**Input**: Design documents from `/specs/005-web-frontend-console/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: INCLUDED. The constitution makes testing non-negotiable (Principle V) and research R11 +
quickstart explicitly request Vitest + React Testing Library + MSW for the SPA and one pytest for the
backend CORS change. Test tasks are first-class below, concentrated on the pure `lib/` logic (the
riskiest code) and the MSW-mocked component/flow tests.

**Organization**: Tasks are grouped by user story (priority order from spec.md) so each story is an
independently testable increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US5; Setup / Foundational / Polish carry no story label
- All paths are repo-relative. Frontend lives in `frontend/`, backend in `backend/`.

## Path & stack reference (from plan.md / contracts)

- Stack: TypeScript 5.6 (strict) · React 18.3 · Vite 5 · **Ant Design 5** · **TanStack Query 5** ·
  **React Router 6** · **Recharts 2**; tests via **Vitest + RTL + MSW**; lint via ESLint + Prettier.
- API base = `VITE_API_BASE_URL` (dev `http://api.localhost`); SPA served at `http://app.localhost`.
- Backend touch = CORS only: `backend/app/settings.py`, `backend/app/main.py`, one pytest.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add the feature's dependencies and quality tooling to the existing Vite app. No app
behavior yet.

- [X] T001 Add runtime deps to `frontend/package.json` (`antd`, `@ant-design/icons`, `@tanstack/react-query`, `react-router-dom`, `recharts`), rename the package to `notification-admin-frontend`, then run `npm install` to refresh `frontend/package-lock.json`.
- [X] T002 [P] Add dev/test deps and scripts to `frontend/package.json` (`msw`, `@testing-library/user-event`, `eslint`, `typescript-eslint`, `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh`, `prettier`); add `"lint"`, `"lint:fix"`, and `"format"` npm scripts (keep existing `dev`/`build`/`test`/`preview`).
- [X] T003 [P] Create ESLint flat config `frontend/eslint.config.js` (typescript-eslint recommended + `react-hooks` + `react-refresh`), scoped to `src/**`.
- [X] T004 [P] Create `frontend/.prettierrc` and `frontend/.prettierignore` (ignore `dist`, `node_modules`, `package-lock.json`).
- [X] T005 [P] Create the MSW test harness: `frontend/src/test/server.ts` (`setupServer`) and `frontend/src/test/handlers.ts` (default happy-path `/api/v1` handlers for auth/contacts/templates/sends) per the api-client contract.
- [X] T006 Wire MSW into `frontend/src/setupTests.ts` (`beforeAll(server.listen)`, `afterEach(server.resetHandlers)`, `afterAll(server.close)`) — depends on T002 (msw) and T005.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Cross-origin enablement, the typed transport seam, the pure `lib/` logic, the session
machinery, and the router/provider/shell skeleton that EVERY user story depends on.

**⚠️ CRITICAL**: No user story can be completed until this phase is done.

### Backend — the one permitted change (CORS), per contracts/backend-cors.md

- [X] T007 [P] Add `cors_allow_origins: list[str] = ["http://app.localhost"]` (env-overridable, never `"*"`) to `backend/app/settings.py`.
- [X] T008 Register `CORSMiddleware` in `create_app()` in `backend/app/main.py` from `get_settings().cors_allow_origins` (`allow_credentials=False`, `allow_methods=["*"]`, `allow_headers=["Authorization","Content-Type"]`, `max_age=600`) — depends on T007.
- [X] T009 Add `backend/tests/integration/test_cors.py`: preflight `OPTIONS /api/v1/auth/login` from the allowed origin asserts the three `Access-Control-Allow-*` headers; a normal request echoes `Access-Control-Allow-Origin`; a disallowed origin gets no such header — depends on T008.

### Frontend — typed transport + pure libs + skeleton

- [X] T010 [P] Create DTO types in `frontend/src/api/types.ts` (`Channel`, `DeliveryState`, `TokenResponse`, `MeResponse`, `Contact`, `ContactCreate`, `Template`, `TemplateCreate`, `DispatchAck`, `Transition`, `Delivery`, `Dispatch`) mirroring data-model.md.
- [X] T011 [P] Implement pure error normalization + status→message mapping in `frontend/src/lib/errors.ts` (`ApiError`, handle both `{detail:string}` and `{detail:[{loc,msg}]}` shapes; produce `fieldErrors` for 422 arrays) per data-model R9.
- [X] T012 [P] Add `frontend/src/lib/errors.test.ts`: both detail shapes → message + `fieldErrors`; 400/401/403/404/409/422 + 5xx/network mapping (drives SC-004).
- [X] T013 [P] Implement pure validators in `frontend/src/lib/validation.ts` (email format, SMS `content ≤ 160`, required fields, password `≥ 8`) mirroring backend rules.
- [X] T014 [P] Add `frontend/src/lib/validation.test.ts` covering each validator (valid/invalid boundaries, SMS 160 edge).
- [X] T015 [P] Implement session storage in `frontend/src/auth/session.ts` (`load`/`save`/`clear` of `{token,email}` under `localStorage` key `nsvc.session`).
- [X] T016 Implement the transport core in `frontend/src/api/http.ts` — `request<T>(method,path,opts)`: prefix `VITE_API_BASE_URL`, attach `Authorization: Bearer`, serialize JSON/urlencoded, parse non-2xx into `ApiError` via `lib/errors`, on `401` clear session + invoke a registered `onUnauthorized`, return parsed JSON or `void` for 204 — depends on T010, T011, T015.
- [X] T017 Create the session context `frontend/src/auth/AuthProvider.tsx` (holds current `Session`, exposes `login(token,email)`/`logout()`, registers `http.ts` `onUnauthorized` → clear session + navigate to `/auth` with an "expired session" message) — depends on T015, T016. (US1 extends it with the `/me` load-probe.)
- [X] T018 Create the route guard `frontend/src/auth/RequireAuth.tsx` (`<Navigate to="/auth" replace>` when no session) — depends on T017.
- [X] T019 [P] Create shared screen-state components in `frontend/src/components/states/` (`Loading.tsx`, `Empty.tsx`, `ErrorState.tsx` with retry) per FR-035 / ui-routes states table.
- [X] T020 Create `frontend/src/components/AppShell.tsx` — AntD `Layout` + top app bar (product name • signed-in email from session • logout) + tab nav (Home/Contacts/Templates/Send & History) with the active tab derived from the URL, rendering `<Outlet/>` (FR-002/003) — depends on T017.
- [X] T021 Create `frontend/src/App.tsx` — provider tree (`QueryClientProvider` with `retry:false` for 4xx, AntD `ConfigProvider` + `App`, `BrowserRouter`, `AuthProvider`) and the route table: public `/auth`, `/verify`, `/reset` → `AuthPage`; `RequireAuth`-guarded shell `/` → `AppShell` with child routes index→`Dashboard`, `/contacts`→`ContactsPage`, `/templates`→`TemplatesPage`, `/sends`→`SendHistoryPage`; `*` redirects per ui-routes.md — depends on T017, T018, T020. (Imports of the four page modules resolve as each story lands; implement in priority order.)
- [X] T022 Swap the app entrypoint in `frontend/src/main.tsx` to render `<App/>`, and remove the demo `frontend/src/components/HealthView.tsx`, `frontend/src/components/HealthView.test.tsx`, and `frontend/src/api/health.ts` — depends on T021.

**Checkpoint**: CORS verified by pytest; transport + pure `lib/` logic unit-tested; the session /
provider / guard / shell wiring is in place. Note that `App.tsx` (T021) imports the five page modules
authored in Phases 3–7, so `tsc --noEmit` / `vite build` and a browseable app first go green once
**US1** lands (making `/auth`, `/verify`, `/reset` resolve) and are fully green only after the stories
you choose to ship — the end-to-end green gate is **T048**. User stories can now proceed in priority
order (or in parallel by story once that story's shared API client exists).

---

## Phase 3: User Story 1 - Authenticate and enter the application (Priority: P1) 🎯 MVP

**Goal**: One auth surface for the whole account lifecycle (login/register/verify/request-reset/
confirm-reset) with `?token=` deep links, landing in the signed-in shell; logout or any 401 returns
to `/auth`.

**Independent Test**: With no session the app opens on `/auth` (Login). Register → prompted to verify;
verify via pasted token and via `/verify?token=` (auto). Log in → shell shows the signed-in email;
log out → back to `/auth`. Request reset (always acknowledged) → confirm with token + new password →
log in. Force a 401 → returned to `/auth`.

- [X] T023 [US1] Implement the auth client in `frontend/src/api/auth.ts` — `register`, `verify` (query token), `login` (**urlencoded** `username`/`password`), `me`, `requestReset`, `confirmReset` — per contracts/api-client.md (depends on T016).
- [X] T024 [US1] Extend `frontend/src/auth/AuthProvider.tsx` with the on-load `GET /auth/me` validity probe (app-level spinner while probing; a 401 clears the stale session) and wire `login()`/`logout()` to persist/clear `session.ts` — depends on T023.
- [X] T025 [US1] Implement `frontend/src/features/auth/AuthPage.tsx` — a single page with all five modes switchable in place (Login default, Register, Verify, Request reset, Confirm reset) using AntD `Form`; client validation via `lib/validation`; surface server errors via `ApiError.detail`/`fieldErrors`; on unverified-login (400) reveal the Verify path (FR-012); success/error toasts via AntD `App.message` — depends on T023, T011, T013, T019.
- [X] T026 [US1] Add deep-link handling to `AuthPage` via `useSearchParams`/route mode: `/verify?token=` auto-submits on load and reports success or a specific failure (invalid/expired/used); `/reset?token=` prefills the token and prompts for a new password (FR-009/011, SC-007) — depends on T025.
- [X] T027 [P] [US1] Add `frontend/src/features/auth/AuthPage.test.tsx` (MSW): default Login; mode switching; register→verify guidance; `/verify` deep-link auto-verify success + invalid-token failure; unverified-login message + Verify path; reset-request always-acknowledged; confirm-reset → directed to login.
- [X] T028 [P] [US1] Add `frontend/src/auth/AuthProvider.test.tsx` (MSW): an authed call returning 401 clears the session and redirects to `/auth` with a message (FR-005, SC-005); stored-session load-probe 401 clears stale session.

**Checkpoint**: US1 fully functional and independently testable — the MVP gate.

---

## Phase 4: User Story 2 - Manage contacts (Priority: P1)

**Goal**: Create a contact (display name + any combo of email/phone/device token) and view a paginated
read-only table; new contacts appear without a manual reload.

**Independent Test**: Sign in → Contacts → create with a name + ≥1 destination → it appears without
reload. Submit with no destination → blocked with a clear message. Page through when there are more
contacts than one page; table is read-only.

- [X] T029 [US2] Implement the contacts client in `frontend/src/api/contacts.ts` — `list(limit≤100, offset)` and `create(body)` per contracts/api-client.md (depends on T016).
- [X] T030 [US2] Implement `frontend/src/features/contacts/ContactsPage.tsx` — create `Form` (display_name + email/phone/device_token; require ≥1 destination client-side and surface the server 422); read-only paginated AntD `Table` over `['contacts']` (limit/offset paging, no row selection/actions); invalidate `['contacts']` on create so the table refreshes without reload (FR-017); loading/empty/error states + toasts — depends on T029, T013, T019.
- [X] T031 [P] [US2] Add `frontend/src/features/contacts/ContactsPage.test.tsx` (MSW): create → appears without reload; no-destination submission blocked client-side; empty state when no contacts; paging shows additional rows.

**Checkpoint**: US1 + US2 both work independently.

---

## Phase 5: User Story 3 - Manage templates (Priority: P2)

**Goal**: Paginated templates table with row-selection-enabled Edit/Delete; create/edit captures
title, content, one channel, and recipients multi-selected from the user's contacts; SMS ≤ 160
enforced client-side and server errors surfaced; delete needs confirmation; editing/deleting never
sends.

**Independent Test**: With ≥1 contact, create a template (channel + recipients) → appears in the
table. Select → edit → save. Switch to SMS, content > 160 → rejected client-side and server 422
surfaced. Delete → confirmation required and nothing is sent.

- [X] T032 [US3] Implement the templates client in `frontend/src/api/templates.ts` — `list`, `create`, `update(id)`, `remove(id)`, `send(id)` per contracts/api-client.md (`send` is consumed by US4; never called from edit/delete) (depends on T016).
- [X] T033 [US3] Implement `frontend/src/features/templates/RecipientSelect.tsx` — AntD `Select mode="multiple"`, searchable, options drawn only from the user's contacts via `contacts.list` (paged) (FR-019) — depends on T029.
- [X] T034 [US3] Implement `frontend/src/features/templates/TemplatesPage.tsx` — paginated AntD `Table` with `rowSelection` enabling Edit/Delete; create/edit `Modal` `Form` (title, content, one-of channel `Select`, `RecipientSelect`); enforce SMS ≤ 160 client-side and surface server 422 (content/channel/recipients incl. recipient-not-owned); delete via `Modal.confirm`; never sends (FR-023); invalidate `['templates']` on create/update/remove; states + toasts — depends on T032, T033, T013, T011, T019.
- [X] T035 [P] [US3] Add `frontend/src/features/templates/TemplatesPage.test.tsx` (MSW): create with channel + recipients → appears; SMS > 160 blocked + server 422 surfaced; select → edit → save with no send; delete → confirm required, no send; picker lists only the user's contacts; recipient-not-owned 422 surfaced.

**Checkpoint**: US1–US3 independently functional.

---

## Phase 6: User Story 4 - Send a template and track delivery (Priority: P2)

**Goal**: Pick a template and send it (accepted-for-background-delivery toast, non-blocking); a history
table of past sends with per-send status; drill into any send for per-recipient state + lifecycle
transitions; statuses refresh via manual refresh + light polling until terminal.

**Independent Test**: Send a valid template → "accepted for delivery" appears quickly (≤2s). The send
appears in history; open it → per-recipient statuses progress queued→sent→delivered/failed on
poll/refresh without a reload. Server-owned stats-report sends never appear.

- [X] T036 [US4] Implement the sends client in `frontend/src/api/sends.ts` — `list(limit≤100, offset)` and `get(id)` (full per-delivery transitions) per contracts/api-client.md (depends on T016).
- [X] T037 [US4] Implement `frontend/src/features/sends/SendHistoryPage.tsx` — send form (pick one template via `templates.list` → `templates.send`; "Accepted for delivery" toast ≤ 2s, non-blocking; surface 400 unsendable / 404; invalidate `['sends']`); history AntD `Table` over `['sends']` with per-send status; `refetchInterval` 4s while any delivery is non-terminal, stop at terminal; manual Refresh = `invalidateQueries`; states + toasts (FR-024–028, SC-010) — depends on T036, T032, T019.
- [X] T038 [US4] Implement `frontend/src/features/sends/SendDetailDrawer.tsx` — AntD `Drawer` showing each recipient's state, destination, failure reason, and the full `transitions[]` timeline; poll `['send', id]` every 4s while open and non-terminal (FR-026/027) — depends on T036.
- [X] T039 [P] [US4] Add `frontend/src/features/sends/SendHistoryPage.test.tsx` (MSW): send → accepted toast quickly; unsendable 400 surfaced with no spurious entry; history lists sends; open detail shows per-recipient + transitions; polling advances statuses without reload then stops at terminal; only backend-returned sends shown (stats-reports excluded, FR-028).

**Checkpoint**: US1–US4 independently functional (the core notification flow is complete).

---

## Phase 7: User Story 5 - Personal sending dashboard (Priority: P3)

**Goal**: Home shows a 24-bar (UTC 00–23) chart of the user's sends-per-hour plus summary stats,
derived client-side from `/sends` with a scan cap and a "recent window" indicator; manual refresh
re-aggregates.

**Independent Test**: With sends, Home shows a 24-bar chart (missing hours = 0) + summary
(total reached-`sent`, dispatches scanned, most recent send time); bars equal an independent `sent`
count over the same history. No qualifying sends → all-zero/empty state. > cap dispatches → "recent
window" indicator. Trigger a send, refresh → re-aggregates.

- [X] T040 [P] [US5] Implement the pure aggregator `frontend/src/lib/aggregate.ts` — `aggregate(dispatches) → {buckets[24], totalSent, dispatchesScanned, mostRecentSentAt, capped}`: for each delivery transition with `to_status==='sent'` and non-null `at`, increment `buckets[new Date(at).getUTCHours()]` and `totalSent`, track max `at`; per-delivery, not per-dispatch (FR-030, R7) — depends on T010.
- [X] T041 [P] [US5] Add `frontend/src/lib/aggregate.test.ts`: bucketing by UTC hour; per-delivery counting; all-zero; null `at` skipped; `mostRecentSentAt`; cap → `capped` (SC-006).
- [X] T042 [US5] Implement `frontend/src/features/home/Dashboard.tsx` — page `sends.list` (`limit=100`, incrementing `offset`) until a short page or the 2,000-dispatch cap (≤ 20 calls) under a loading state; run `aggregate`; render a Recharts 24-bar `BarChart` in a `ResponsiveContainer` (00–23, missing = 0) + summary stats; "recent window" indicator when `capped` (FR-033); all-zero empty state (FR-032); manual Refresh re-aggregates (`['dashboard']`); error + retry — depends on T040, T036, T019.
- [X] T043 [P] [US5] Add `frontend/src/features/home/Dashboard.test.tsx` (MSW): bars equal an independent `sent` count; empty state when none; capped indicator when over the cap; refresh re-aggregates.

**Checkpoint**: All five user stories independently functional.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Quality gates, CI/pre-commit wiring, accessibility, and end-to-end validation.

- [X] T044 [P] Run `npm run lint` and `npm run format` in `frontend/` and resolve all ESLint/Prettier findings across the new `src/**` code.
- [X] T045 Extend the `frontend` job in `.github/workflows/ci.yml` to run `npm run lint` and the typecheck (`npm run build` already runs `tsc --noEmit`) so the frontend gate is install → lint → typecheck → test → build (Principle I/VII).
- [X] T046 [P] Add frontend ESLint/Prettier hooks for `frontend/**` to `.pre-commit-config.yaml`.
- [X] T047 Accessibility & responsive pass (FR-038): labeled form fields, keyboard navigability, sufficient contrast, and `scroll-x` on tables at tablet widths across all feature pages under `frontend/src/features/`.
- [X] T048 Verify the full frontend gate is green: `npm run build` (`tsc --noEmit && vite build`) + `npm run test` in `frontend/`, and `uv run pytest tests/integration/test_cors.py` in `backend/`.
- [X] T049 [P] Add a short frontend overview to `frontend/README.md` (dev loop, `VITE_API_BASE_URL`, scripts) consistent with the repo's docs style.
- [ ] T050 Execute the quickstart.md end-to-end validation (all nine browser flows at `http://app.localhost`).

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies — start immediately.
- **Foundational (Phase 2)**: depends on Setup; **blocks all user stories**. The backend CORS chain
  (T007→T008→T009) is independent of the frontend skeleton and can proceed fully in parallel.
- **User Stories (Phase 3–7)**: each depends on Foundational. Recommended order P1→P2→P3, but US2–US5
  can be staffed in parallel once Foundational is done (see story dependencies below).
- **Polish (Phase 8)**: after the stories you intend to ship are complete.

### Story dependencies

- **US1 (P1)**: depends only on Foundational. MVP.
- **US2 (P1)**: depends only on Foundational. Independent of US1 at the code level (auth is the runtime
  gate, not a build dependency).
- **US3 (P2)**: uses `contacts.list` (T029) for the recipient picker — start US3 after T029 exists.
- **US4 (P2)**: uses `templates.send`/`templates.list` (T032) — start US4 after T032 exists.
- **US5 (P3)**: uses `sends.list` (T036) — start US5 after T036 exists. Otherwise independent.

### Within each task pairing

- Each `*.test.ts(x)` follows the module it covers (e.g., T012 after T011, T041 after T040).
- Models/types before clients; clients before pages; pages before their flow tests.

### Parallel opportunities

- Setup: T002, T003, T004, T005 in parallel (then T006).
- Foundational: the whole backend CORS chain runs parallel to the frontend skeleton; T010/T011/T013/
  T015/T019 (+ their tests T012/T014) are parallel pure-file tasks before the http/provider chain
  (T016→T017→T018→T020→T021→T022).
- Across stories: once Foundational + the one shared client per story exist, US2–US5 pages and their
  `[P]` tests can be built concurrently by different developers.

---

## Parallel Example: Foundational pure libs

```bash
# After Setup, launch the independent pure-file tasks together:
Task T010: "Create DTO types in frontend/src/api/types.ts"
Task T011: "Implement frontend/src/lib/errors.ts"
Task T013: "Implement frontend/src/lib/validation.ts"
Task T015: "Implement frontend/src/auth/session.ts"
Task T019: "Create frontend/src/components/states/ wrappers"
# ...and the backend CORS chain in parallel:
Task T007: "Add cors_allow_origins to backend/app/settings.py"
```

---

## Implementation Strategy

### MVP first (US1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational (incl. CORS) → 3. Phase 3 US1 → **STOP & VALIDATE** the
auth gate end-to-end (SC-001/002/005/007), then demo.

### Incremental delivery

Foundation → US1 (auth) → US2 (contacts) → US3 (templates) → US4 (send & history) → US5 (dashboard).
Each story is a shippable increment; US4 completes the headline notification flow, US5 adds insight.

### Parallel team strategy

After Foundational, one developer takes US1 while another lands the shared clients (T029/T032/T036),
unblocking US2/US3/US4/US5 to proceed concurrently.
