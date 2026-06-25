# Implementation Plan: Enterprise Admin Web Frontend

**Branch**: `005-web-frontend-console` | **Date**: 2026-06-24 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-web-frontend-console/spec.md`

## Summary

Build the complete enterprise-admin SPA in the existing `frontend/` (React + Vite + TypeScript),
consuming the existing `/api/v1` backend: a single auth surface (login / register / verify / reset-
request / reset-confirm with `?token=` deep links), a signed-in shell (top app bar + Home / Contacts
/ Templates / Send & History tabs), a client-side per-UTC-hour sending dashboard derived from
`/sends`, contact create+list, template CRUD with a contacts-backed recipient picker and channel
rules, and template sending + delivery-status history with light polling. UI is built on **Ant
Design 5**; server state and polling via **TanStack Query**; routing/deep-links via **React Router**;
the 24-bar chart via **Recharts**. The one backend change — explicitly clarified in the spec — is
adding **FastAPI `CORSMiddleware`** (allowed origins from `pydantic-settings`) so the browser SPA at
`http://app.localhost` can call the API at `http://api.localhost`. No business endpoint, schema, or
notification/resilience behavior changes.

## Technical Context

**Language/Version**: TypeScript 5.6 (strict) on React 18.3; built with Vite 5; Node 18 build stage
(existing image). Backend touch: Python 3.13 / FastAPI (existing).

**Primary Dependencies** (frontend, added): `antd` 5 (+ `@ant-design/icons`), `@tanstack/react-query`
5, `react-router-dom` 6, `recharts` 2. Dev/test: `msw` 2, `@testing-library/user-event`, plus the
existing `vitest` + `@testing-library/react` + `jsdom`. Lint/format: `eslint` + `typescript-eslint` +
`eslint-plugin-react-hooks` + `prettier` (the frontend analog of the backend's ruff/mypy gate).
Backend (added): none new — only Starlette's bundled `CORSMiddleware`.

**Storage**: Browser `localStorage` for the access token + the login email (session persistence
across reload). No new server-side storage. The dashboard aggregate is computed in-memory, not
persisted (FR-030).

**Testing**: Frontend — Vitest + React Testing Library + MSW (mocked `/api/v1`); pure-function unit
tests for the per-hour aggregation, error mapping, and validators; component/flow tests for auth,
contacts, templates, send. Backend — one pytest asserting the CORS preflight/headers via the FastAPI
test client (no DB needed).

**Target Platform**: Evergreen desktop + tablet browsers; served as a static bundle by nginx
(existing multi-stage image), reached at `http://app.localhost`.

**Project Type**: Web application — frontend SPA plus a minimal, explicitly-scoped backend CORS touch.

**Performance Goals**: Send-acceptance toast within 2s (SC-010; backend returns 202 immediately).
Dashboard aggregation pages `/sends` sequentially (`limit=100`) up to a 2,000-dispatch cap (≤ 20
calls) under a loading state. Status freshness via ~4s polling while any delivery is non-terminal.

**Constraints**: Cross-origin is enabled only via CORS (the one permitted backend change, FR-040);
the dashboard is derived entirely client-side from `/sends` with no new endpoint (FR-030); paginated
lists use the backend `limit ≤ 100` + `offset` paging (FR-039); server is the source of truth for
validation, and both error-body shapes (`{detail: string}` for domain errors, `{detail: [...]}` for
FastAPI request-validation) MUST be handled (FR-037).

**Scale/Scope**: Single admin user per session. ~5 route groups, 4 feature areas, ~15–20 components.
Per-user contacts/templates are modest (tens–hundreds); send history can be large and is bounded by
the dashboard scan cap and table paging.

## Constitution Check

*GATE: evaluated against `.specify/memory/constitution.md` v1.5.0. The constitution is backend-
oriented; each principle is mapped to its frontend analog or marked N/A.*

| Principle | Status | Notes |
|---|---|---|
| I. Code Quality (typed, linted, observable) | PASS | TS `strict` already on (`tsc --noEmit` in `build`). Add ESLint + Prettier as the ruff/mypy analog, wired into the frontend CI job and pre-commit. CORS allowed-origins are modeled in `pydantic-settings` (no ad-hoc `os.environ`, no hard-coding). Browser error/observability (Sentry SPA) is **not** in scope — the constitution's structlog/OTel/Sentry mandate targets the Python application; the SPA surfaces errors via toasts/empty-error states. |
| II. Architecture (hexagonal, proportionate, open for extension) | PASS | Frontend layered as `api/` (transport + typed clients) → feature modules → shared components; pure logic isolated in `lib/`. The CORS change is app-wiring in `main.py`, not domain — domain/ports/adapters untouched. |
| III. Background Processing | N/A | No Celery/worker change; the SPA only reads the lifecycle the workers already persist. |
| IV. Resilience | N/A (consumed) | The app surfaces the persisted `queued → sent → delivered \| failed` lifecycle and polls for progress; it adds no retry/breaker logic of its own and changes none. |
| V. Testing (real PG + broker, mocked HTTP) | PASS | Frontend tests mock the HTTP boundary with MSW (the SPA's analog of `respx`). The backend CORS change ships with a pytest assertion on preflight/headers using the FastAPI test client (no DB/broker required, so no Testcontainers needed for this assertion). |
| VI. Security (tokens, hashing, secrets) | PASS | OAuth2 password login → JWT sent as a `Bearer` header on every call; no new auth scheme. CORS uses an explicit allow-list (no `*`) sourced from settings, `allow_credentials=False` (Bearer header, not cookies). `localStorage` token persistence is documented with its XSS trade-off in research R6. |
| VII. Operations (Docker, GH Actions, k8s) | PASS | Reuses the existing multi-stage frontend image and nginx SPA fallback; no process-model change. `VITE_API_BASE_URL` stays build-arg driven; CORS origins are env-configurable per environment. CI gains a frontend job (install → lint → typecheck → test → build). |

**Result**: PASS, no violations. Complexity Tracking not required. The CORS addition is the spec's
single clarified backend change (it unblocks a browser SPA from calling the API at all) and is
config-driven + tested, so it is compliant rather than a deviation.

## Project Structure

### Documentation (this feature)

```text
specs/005-web-frontend-console/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions (CORS, AntD, Query, Router, Recharts, storage, aggregation…)
├── data-model.md        # Phase 1 — client DTO/view types, validation rules, lifecycle, aggregation spec
├── quickstart.md        # Phase 1 — run + end-to-end validation guide
├── contracts/
│   ├── backend-cors.md  #   the one backend change: CORS settings + middleware contract + acceptance
│   ├── ui-routes.md     #   route table, guards, deep-link behavior, navigation
│   └── api-client.md    #   typed client surface mapping to /api/v1 + error normalization
└── checklists/
    └── requirements.md  # (from /speckit-specify)
```

### Source Code (repository root)

```text
frontend/
├── src/
│   ├── api/
│   │   ├── http.ts            # fetch core: base URL, Bearer header, 401 hook, ApiError normalization
│   │   ├── types.ts           # DTO types mirroring backend schemas (Contact, Template, Dispatch…)
│   │   ├── auth.ts            # register / verify / login / me / reset-request / reset-confirm
│   │   ├── contacts.ts        # list (paged) / create
│   │   ├── templates.ts       # list (paged) / create / update / remove / send
│   │   └── sends.ts           # list (paged) / get one
│   ├── auth/
│   │   ├── session.ts         # token+email storage, get/set/clear
│   │   ├── AuthProvider.tsx   # context: current session, login/logout, onUnauthorized wiring
│   │   └── RequireAuth.tsx    # route guard → redirects to /auth when no session
│   ├── lib/
│   │   ├── aggregate.ts       # PURE: dispatches[] → 24 hour buckets + summary (FR-030/031/033)
│   │   ├── errors.ts          # PURE: ApiError → user message + field errors (both detail shapes)
│   │   └── validation.ts      # PURE: email, SMS≤160, required, password≥8 (mirror backend)
│   ├── components/
│   │   ├── AppShell.tsx       # Layout + top app bar (product, user email, logout) + tab nav
│   │   ├── states/            # Loading / Empty / ErrorState wrappers (FR-035)
│   │   └── ...                # shared table/form bits
│   ├── features/
│   │   ├── auth/AuthPage.tsx          # Login/Register/Verify/ResetRequest/ResetConfirm modes
│   │   ├── home/Dashboard.tsx         # summary stats + 24-bar Recharts chart + refresh
│   │   ├── contacts/ContactsPage.tsx  # create form + read-only paginated table
│   │   ├── templates/TemplatesPage.tsx# table + selection + create/edit modal + recipient picker + delete confirm
│   │   └── sends/SendHistoryPage.tsx  # send form + history table + per-recipient detail drawer (polling)
│   ├── App.tsx               # Router + providers (QueryClient, AntD ConfigProvider+App, AuthProvider)
│   ├── main.tsx              # root render → <App/> (replaces the HealthView demo mount)
│   └── *.test.ts(x)          # Vitest tests alongside sources
├── .eslintrc.cjs / eslint.config.js   # ESLint + typescript-eslint + react-hooks
├── .prettierrc                        # Prettier
├── package.json                       # + deps/scripts (lint, format, test); lockfile committed
└── (existing) Dockerfile, nginx.conf, vite.config.ts, tsconfig.json

backend/
├── app/settings.py          # + cors_allow_origins: list[str] (default ["http://app.localhost"])
├── app/main.py              # + app.add_middleware(CORSMiddleware, …) from settings
└── tests/.../test_cors.py   # asserts preflight + Access-Control-Allow-Origin for an allowed origin
```

**Structure Decision**: Web application. The frontend follows the constitution's `frontend/` layout
with a clear `api/` transport seam, isolated pure `lib/` logic (the riskiest, most testable code),
feature modules per tab, and shared shell/state components. The backend is touched in exactly two
files plus one test — the minimal, config-driven CORS enablement clarified in the spec.

## Complexity Tracking

No constitution violations — section intentionally empty. The deliberate stack breadth (Celery,
observability, etc.) is unaffected by this frontend feature and is not a deviation per the
constitution's Technology Stack section.
