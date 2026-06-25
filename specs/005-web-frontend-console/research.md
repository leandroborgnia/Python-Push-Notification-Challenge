# Research: Enterprise Admin Web Frontend

Phase 0 decisions. Each item: **Decision**, **Rationale**, **Alternatives considered**. Open
spec assumptions (token storage, scan cap, polling cadence, library choices, deep-link routing) are
resolved here.

## R1 — Cross-origin strategy (the one backend change)

- **Decision**: Add FastAPI/Starlette **`CORSMiddleware`** in `app/main.py`, with the allowed-origins
  list sourced from a new `pydantic-settings` field `cors_allow_origins` (dev default
  `["http://app.localhost"]`; env-overridable per environment). `allow_credentials=False`,
  `allow_methods=["*"]`, `allow_headers=["Authorization", "Content-Type"]`. The SPA keeps calling the
  API cross-origin at `VITE_API_BASE_URL` (`http://api.localhost` in dev).
- **Rationale**: As shipped, the dev build serves the SPA at `app.localhost` and points it at
  `api.localhost`; with no CORS anywhere, a browser blocks every authenticated call. The spec was
  clarified (Session 2026-06-24) to permit this single minimal change. In-code middleware is
  **environment-portable** (identical in dev/test/prod and under the FastAPI test client), explicit,
  and **unit-testable**, and modeling origins in `pydantic-settings` satisfies Principle I/VI
  (config-driven, no hard-coding, explicit allow-list — never `*` with credentials). Bearer-token
  auth means no cookies, so `allow_credentials=False` is correct and avoids the `*`-origin pitfall.
- **Alternatives considered**:
  - *Same-origin via ingress* (add an `/api` path on the `app.localhost` host → `notification-api`,
    point the SPA at same-origin `/api/v1`): no CORS at all and matches the 003 contract's declared
    server, but bakes the topology into ingress manifests and behaves differently under the test
    client / non-nginx ingress controllers. Rejected for less portability/testability.
  - *Ingress-level CORS annotations* on `api.localhost`: deploy-only, but nginx-ingress-specific,
    invisible to `pytest`, and untested in CI. Rejected for the same reason.
  - *No change*: not viable — the browser blocks all calls.

## R2 — Component library

- **Decision**: **Ant Design 5** (`antd` + `@ant-design/icons`), with the App-level `App` component
  for context-aware `message` (toasts) and `Modal.confirm`, and `ConfigProvider` for theming tokens.
- **Rationale**: `Table` (built-in pagination + `rowSelection`), `Form` (field-level validation +
  async server-error surfacing), `Tabs`, `Layout`, `Select` (multi-select recipient picker),
  `Drawer`/`Modal`, and `message` map 1:1 onto every UI requirement (FR-002/003, FR-016/018/019/022,
  FR-035/036). It is the canonical enterprise-admin look, first-class TypeScript, zero hand-rolled
  primitives (honors the "prefer libraries" preference).
- **Alternatives considered**: *MUI* (excellent but Material aesthetic, table pagination/selection
  needs more wiring or MUI X DataGrid); *Mantine* (great DX, smaller table ecosystem). Both viable;
  AntD is the closest fit to "data-dense enterprise admin" out of the box.

## R3 — Server-state & async layer

- **Decision**: **TanStack Query 5** (`@tanstack/react-query`) for all reads/mutations; one
  `QueryClient` with `retry: false` for 4xx and sane defaults; query keys per resource
  (`['contacts']`, `['templates']`, `['sends']`, `['send', id]`).
- **Rationale**: Built-in caching, background refetch, `refetchInterval` (status polling, FR-027),
  `invalidateQueries` (manual refresh, FR-017/034), and request de-duplication — exactly the
  cross-cutting needs, without hand-rolling loading/error/stale state. Pairs cleanly with AntD's
  loading/empty/error rendering.
- **Alternatives considered**: *SWR* (lighter, fewer mutation/polling ergonomics); *hand-rolled
  `useEffect` + `useState`* (re-implements caching/polling/dedupe — rejected per "prefer libraries").

## R4 — Routing & deep links

- **Decision**: **React Router 6** (`react-router-dom`). Routes: `/auth` (with sub-modes via query/
  path), `/verify` and `/reset` as dedicated deep-link landing routes that read `?token=`, and the
  authed shell at `/` with child routes `/` (Home), `/contacts`, `/templates`, `/sends`. A
  `RequireAuth` wrapper guards the shell; absence of a session redirects to `/auth`.
- **Rationale**: Verification and reset-confirm must work from an emailed `?token=` deep link
  (FR-009/011, SC-007). Distinct landing routes let the app know *which* token flow to run (the
  ambiguity flagged in the spec's deep-link assumption). React Router is the standard, integrates with
  the nginx history-fallback already configured in `nginx.conf`.
- **Alternatives considered**: *Hash routing* (ugly deep-link URLs); *single-state switch without a
  router* (loses real URLs/back-button, complicates deep links). Rejected.

## R5 — Charting

- **Decision**: **Recharts 2** for the 24-bar per-UTC-hour `BarChart` (`ResponsiveContainer`).
- **Rationale**: Lightweight, declarative, SVG, responsive, UI-library-agnostic; a 24-category bar
  chart with an empty/all-zero state is trivial. No dependency coupling to the UI kit.
- **Alternatives considered**: *`@ant-design/plots`/`@ant-design/charts`* (heavier, pulls G2);
  *Chart.js/react-chartjs-2* (canvas, imperative); *visx* (lower-level). Recharts is the best
  size/ergonomics fit for one simple chart.

## R6 — Session storage, identity & 401 handling

- **Decision**: Persist `{ access_token, email }` in **`localStorage`** (key `nsvc.session`). The
  `http.ts` core attaches `Authorization: Bearer <token>`; any `401` clears the session and invokes a
  registered `onUnauthorized` callback that routes to `/auth` (FR-005). On app load with a stored
  token, call `GET /api/v1/auth/me` once as a validity probe; a 401 there clears the stale session.
  The app bar shows the stored `email` (since `/me` returns only `user_id`).
- **Rationale**: `localStorage` survives reload (good UX for an admin tool) and there is no refresh-
  token flow, so token expiry simply ends the session at the next 401. Storing the login email avoids
  needing a backend change to surface identity.
- **Trade-off / mitigation**: `localStorage` is readable by injected scripts (XSS). Accepted for this
  portfolio app; mitigated by AntD's escaping, no `dangerouslySetInnerHTML`, and a short access-token
  TTL (30 min, per backend settings). Documented rather than hidden. (A in-memory + silent-refresh
  scheme is the hardened alternative but requires a refresh endpoint the backend does not provide.)
- **Alternatives considered**: *`sessionStorage`* (lost on tab close — worse UX, same XSS surface);
  *in-memory only* (lost on reload, forces re-login constantly).

## R7 — Dashboard per-hour aggregation

- **Decision**: A **pure** `aggregate(dispatches)` in `lib/aggregate.ts` returning `{ buckets:
  number[24], totalSent, dispatchesScanned, mostRecentSentAt, capped }`. Algorithm: for each
  dispatch, for each delivery, for each transition with `to_status === 'sent'` and a non-null `at`,
  increment `buckets[new Date(at).getUTCHours()]` and `totalSent`; track the max `at` as
  `mostRecentSentAt`. The page fetches `/sends` with `limit=100`, incrementing `offset`, until a page
  returns `< 100` (exhausted) **or** `dispatchesScanned` reaches the **2,000** cap (≤ 20 calls); set
  `capped=true` if the cap stopped it (FR-033).
- **Rationale**: Matches the backend's emailed-graph definition exactly — count per-recipient
  deliveries that reached `sent`, bucket by the UTC hour of that transition (FR-030). `/sends` already
  returns full per-delivery transitions in the list response, so no per-dispatch calls are needed.
  Keeping it a pure function makes it the unit-test centerpiece (SC-006). All-zero buckets render the
  empty state (FR-032).
- **Cap = 2,000 dispatches**: 20 sequential `limit=100` pages, ~1–2s under a loading state — a
  sensible bound for "recent window"; tunable via a module constant. Most-recent-send time uses the
  max `sent`-transition `at` (falls back to dispatch `created_at` if no `sent` yet).
- **Edge**: transitions with null `at` (shouldn't occur for a real `sent`) are skipped, not bucketed.
- **Alternatives considered**: per-dispatch `/sends/{id}` fan-out (unnecessary — list already carries
  transitions); a backend aggregation endpoint (explicitly out of scope, FR-030/040).

## R8 — Send-status freshness (polling)

- **Decision**: Use TanStack Query `refetchInterval` on `['sends']` and on an open `['send', id]`
  detail: poll every **4s** while any visible delivery is non-terminal (`queued`/`sent`), and stop
  (return `false`) once all are terminal (`delivered`/`failed`). A manual **Refresh** button calls
  `invalidateQueries`.
- **Rationale**: Background delivery progresses asynchronously (FR-027); polling + manual refresh is
  the spec's chosen mechanism (websockets are out of scope). 4s balances freshness vs. load; stopping
  at terminal avoids needless traffic.
- **Alternatives considered**: fixed always-on polling (wasteful), manual-only (stale without action).

## R9 — Error mapping (server is source of truth)

- **Decision**: `lib/errors.ts` normalizes responses in `http.ts` into `ApiError { status, detail,
  fieldErrors? }`, handling **both** backend shapes: domain errors return `{ detail: string }` (400/
  403/404/409/422), while FastAPI request-validation returns `{ detail: [{ loc, msg, type }] }`. The
  mapper produces a human message per status (e.g., 409 → "That email is already registered."; 422 →
  the specific field message; 404 → "Not found or no longer available."; 403 → "Not allowed.") and,
  when a validation array is present, a `fieldErrors` map to drive AntD `Form` field errors.
- **Rationale**: FR-036/037 + SC-004 require specific, actionable messages and server-authoritative
  validation. The dual-shape handling is essential because login-of-unverified and bad-credentials
  both return **400 `{detail}`** — the mapper surfaces the server `detail`, and the Auth page
  additionally offers the Verify path when the message indicates verification is required (FR-012).
- **Alternatives considered**: trusting only HTTP status (loses the specific domain message); only
  handling `{detail: string}` (breaks on FastAPI 422 arrays). Rejected.

## R10 — Frontend quality tooling (Principle I analog)

- **Decision**: Add **ESLint** (`eslint` + `typescript-eslint` + `eslint-plugin-react-hooks` +
  `eslint-plugin-react-refresh`) and **Prettier**; npm scripts `lint`, `format`, plus existing
  `build` (`tsc --noEmit && vite build`) and `test`. Wire a **frontend CI job** (install → lint →
  typecheck → test → build) and add frontend lint/format to pre-commit.
- **Rationale**: The constitution mandates lint+format+typecheck gates; for the React app the analog
  is ESLint+Prettier+`tsc`. Keeps the SPA legible and consistent with the repo's quality posture.
- **Alternatives considered**: Biome (single fast tool) — viable, but ESLint+Prettier is the most
  conventional React setup and lowest-surprise for reviewers.

## R11 — Frontend testing approach (Principle V analog)

- **Decision**: **Vitest + React Testing Library + MSW**. MSW mocks `/api/v1` at the network boundary
  (the SPA analog of `respx` — mock HTTP, not internals). Heavy unit coverage on pure `lib/`
  (`aggregate`, `errors`, `validation`); component/flow tests for: auth mode switching + deep-link
  verify, contact create→list refresh, template create/edit/delete + SMS-160 rule, send→history→
  detail with polling, and 401→redirect. The backend CORS change ships one pytest asserting preflight
  + `Access-Control-Allow-Origin` via the FastAPI test client.
- **Rationale**: Mirrors the constitution's "mock only the HTTP boundary" rule and concentrates
  effort on the riskiest logic (aggregation correctness, SC-006). MSW keeps tests realistic without a
  live backend.
- **Alternatives considered**: full e2e (Playwright) — valuable but heavier; deferred (MSW component
  tests cover the flows for this feature). Mocking the client modules directly — rejected (mocks the
  wrong seam).

## Resolved spec assumptions

| Spec assumption | Resolution |
|---|---|
| Token storage mechanism | `localStorage` (R6), XSS trade-off documented |
| Dashboard scan cap | 2,000 dispatches / 20 pages of 100 (R7), module constant |
| Polling cadence | 4s while non-terminal, stop at terminal (R8) |
| Deep-link routing for verify vs reset | distinct `/verify` and `/reset` landing routes (R4) |
| Component & charting libraries | Ant Design 5 (R2) + Recharts (R5) |
| Cross-origin handling | FastAPI `CORSMiddleware`, origins from settings (R1) |
