# Quickstart: Enterprise Admin Web Frontend

Run and validate the SPA end-to-end against the existing backend. References:
[plan.md](./plan.md) · [contracts/](./contracts/) · [data-model.md](./data-model.md).

## Prerequisites

- The full stack up on the local kind cluster: `./up-dev.ps1` (Windows → WSL) or `scripts/up-dev.sh`.
  Brings up api + cpu/io workers + postgres + rabbitmq + **mailpit** + frontend, reachable at
  `http://app.localhost` (API at `http://api.localhost`).
- The CORS change ([backend-cors.md](./contracts/backend-cors.md)) deployed (allowed origin
  `http://app.localhost`) — without it the browser blocks every call.
- **Mailpit** (dev mail catcher) for reading verification/reset tokens — open its web UI to copy the
  emailed `?token=` links.

## Frontend dev loop (host)

```bash
cd frontend
npm install                 # installs antd, @tanstack/react-query, react-router-dom, recharts, msw, eslint…
npm run dev                 # Vite dev server (set VITE_API_BASE_URL=http://api.localhost)
npm run lint                # ESLint (added)
npm run build               # tsc --noEmit && vite build (typecheck + bundle)
npm run test                # Vitest (unit + MSW component/flow tests)
```

Backend CORS test (host, in `backend/`): `uv run pytest tests/.../test_cors.py`.

## End-to-end validation (maps to user stories & success criteria)

1. **Auth gate (US1, SC-001)** — Visit `http://app.localhost` with no session ⇒ lands on `/auth`
   (Login). Switch modes and confirm all five are present in one place.
2. **Register → verify (US1, SC-002/007)** — Register an email+password ⇒ prompted to verify. Open
   Mailpit, click the verification link (`/verify?token=…`) ⇒ the app auto-verifies. (Also paste a
   token manually to confirm both paths.)
3. **Login (US1, SC-001)** — Log in ⇒ land in the shell; app bar shows the product name, your email,
   and Logout. Attempt login on an unverified account ⇒ clear "verify first" message + Verify path
   (FR-012).
4. **Session expiry (US1, SC-005)** — Tamper/expire the stored token (or wait past TTL) and trigger a
   call ⇒ redirected to `/auth` with an "expired session" message. Re-login restores access.
5. **Reset (US1)** — Request reset for any email ⇒ always acknowledged. Use the Mailpit link
   (`/reset?token=…`) + a new password ⇒ directed to log in with it.
6. **Contacts (US2, FR-014–017)** — Create a contact with a display name + at least one destination ⇒
   appears in the table without reload. Submit with no destination ⇒ blocked with a clear message.
7. **Templates (US3, FR-018–023, SC-004)** — Create a template (title, content, channel, recipients
   from your contacts). Set channel = SMS and content > 160 chars ⇒ rejected client-side and (force a
   server attempt) the server 422 is surfaced. Select a row → edit → save. Delete → confirm prompt
   required; nothing is sent.
8. **Send & history (US4, SC-003/010)** — Pick a template → Send ⇒ "Accepted for delivery" toast
   within ~2s. The send appears in history; open it ⇒ per-recipient state + transition timeline.
   Watch statuses advance (queued→sent→delivered/failed) via polling/refresh without a page reload.
   Confirm server-owned stats-report sends never appear (FR-028).
9. **Dashboard (US5, SC-006/009)** — Open Home ⇒ 24-bar (00–23) chart + summary (total reached-`sent`,
   dispatches scanned, most recent send time). Independently count `sent` transitions over `/sends`
   and confirm the bars match. A brand-new user with no qualifying sends ⇒ all-zero/empty state. With
   > 2,000 dispatches ⇒ the "recent window" indicator appears. Trigger a send, refresh ⇒ re-aggregates.

## Automated-test checklist

- `lib/aggregate` unit tests: bucketing by UTC hour, per-delivery counting, all-zero, cap → `capped`,
  null `at` skipped, `mostRecentSentAt` (SC-006).
- `lib/errors` unit tests: both `{detail}` shapes → message + `fieldErrors`; 401/403/404/409/422
  mapping (SC-004).
- `lib/validation` unit tests: email, SMS≤160, required, password≥8.
- Component/flow (MSW): auth mode-switch + deep-link verify; contact create→refresh; template
  create/edit/delete + SMS rule; send→history→detail polling; 401→redirect.
- Backend: CORS preflight + `Access-Control-Allow-Origin` (allowed vs disallowed origin).

## Done when

All nine flows pass in a browser at `http://app.localhost`, `npm run lint`/`build`/`test` are green,
and the backend CORS test passes — with no business endpoint/schema/behavior change beyond CORS.
