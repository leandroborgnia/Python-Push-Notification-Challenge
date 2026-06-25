# Notification Admin Console (frontend)

The enterprise-admin SPA for the notification service — a React + Vite + TypeScript app built on
**Ant Design 5**, **TanStack Query 5**, **React Router 6**, and **Recharts 2**. It consumes the
existing `/api/v1` backend: a single auth surface (login / register / verify / reset), a signed-in
shell (Home / Contacts / Templates / Send & History), contact and template management, template
sending with delivery tracking, and a client-side per-UTC-hour sending dashboard.

See the feature spec under [`specs/005-web-frontend-console/`](../specs/005-web-frontend-console/)
for the full design (plan, contracts, data model, quickstart).

## Dev loop

```bash
cd frontend
npm install
VITE_API_BASE_URL=http://api.localhost npm run dev   # Vite dev server (host-exposed)
```

The app calls the API cross-origin at `VITE_API_BASE_URL`. In the kind dev stack the SPA is served at
`http://app.localhost` and the API at `http://api.localhost`; the backend enables CORS for the SPA
origin (see [`contracts/backend-cors.md`](../specs/005-web-frontend-console/contracts/backend-cors.md)).
For the full stack, bring it up with `./up-dev.ps1` (Windows → WSL) or `scripts/up-dev.sh`.

## Configuration

| Variable | Purpose | Dev value |
|---|---|---|
| `VITE_API_BASE_URL` | Base URL the SPA prefixes onto every `/api/v1` call | `http://api.localhost` |

The access token + login email are persisted in `localStorage` (key `nsvc.session`); any `401`
clears the session and returns to `/auth`.

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Vite dev server with HMR |
| `npm run build` | `tsc --noEmit` (typecheck) + `vite build` (production bundle) |
| `npm run preview` | Serve the built bundle locally |
| `npm test` | Vitest unit + MSW-mocked component/flow tests |
| `npm run lint` | ESLint (typescript-eslint + react-hooks) over `src/**` |
| `npm run lint:fix` | ESLint with autofix |
| `npm run format` | Prettier write |

## Layout

```text
src/
  api/        transport core (http.ts) + typed clients (auth, contacts, templates, sends)
  auth/       session storage, AuthProvider (login/logout, 401 + on-load probe), RequireAuth guard
  lib/        PURE logic (aggregate, errors, validation) — the unit-test centerpiece
  components/ AppShell + shared Loading/Empty/ErrorState
  features/   auth · home (dashboard) · contacts · templates · sends, one module per tab
  test/       MSW server + handlers, renderWithProviders helper
```

Tests mock only the HTTP boundary with **MSW** (the SPA analog of the backend's `respx`), concentrating
coverage on the pure `lib/` logic and the MSW-driven component flows.
