# Contract: UI Routes, Guards & Screen States

Routing via React Router 6. The nginx SPA history-fallback (`nginx.conf`) already serves `index.html`
for unknown paths, so deep links resolve client-side.

## Route table

| Path | Auth | Screen | Notes |
|---|---|---|---|
| `/auth` | public | `AuthPage` | Default surface when no session. Modes: Login (default), Register, Verify, Request reset, Confirm reset — switchable in place (FR-006). |
| `/verify?token=…` | public | `AuthPage` (Verify mode) | Deep-link landing; auto-submits the token on load and reports success/failure (FR-009, SC-007). Pasted-token entry also available. |
| `/reset?token=…` | public | `AuthPage` (Confirm-reset mode) | Deep-link landing; prefills the token, prompts for a new password (FR-011, SC-007). |
| `/` | **required** | `AppShell` → `Dashboard` (Home) | 24-bar chart + summary + refresh (FR-029–034). |
| `/contacts` | **required** | `AppShell` → `ContactsPage` | Create form + read-only paginated table (FR-014–017). |
| `/templates` | **required** | `AppShell` → `TemplatesPage` | Table + row selection + create/edit modal + delete confirm (FR-018–023). |
| `/sends` | **required** | `AppShell` → `SendHistoryPage` | Send form + history table + detail drawer w/ polling (FR-024–028). |
| `*` (authed) | required | redirect to `/` | Unknown authed path. |
| `*` (no session) | public | redirect to `/auth` | Anything when unauthenticated. |

## Guards & session transitions

- **`RequireAuth`** wraps the shell routes: if no `Session`, `<Navigate to="/auth" replace>`.
- **On app load**: if a stored session exists, fire `GET /api/v1/auth/me` once as a validity probe; a
  401 clears the stale session (then the guard redirects). While probing, show an app-level spinner.
- **Global 401 (FR-005)**: `http.ts` invokes `onUnauthorized` on any 401 → clear session → route to
  `/auth` with an "expired session" message, from whatever screen the user was on.
- **Login success** ⇒ navigate to the intended route or `/`. **Logout** ⇒ clear session ⇒ `/auth`.
- **Active tab** is derived from the URL (FR-003); the app bar (product name • signed-in email •
  logout) is always present in the shell (FR-002).

## Per-screen states (FR-035 — every screen has all three)

| Screen | Loading | Empty | Error |
|---|---|---|---|
| Dashboard | aggregating spinner while paging `/sends` | all-zero chart + "no sends yet" (FR-032) | error panel + retry; toast |
| Contacts | table skeleton/spinner | "No contacts yet — add your first" | error panel + retry; toast |
| Templates | table skeleton/spinner | "No templates yet" | error panel + retry; toast |
| Send & History | table skeleton; per-row status updates on poll | "No sends yet" | error panel + retry; toast |
| Auth (each mode) | submit button busy state | n/a | inline field errors + form-level alert/toast |

## Cross-cutting UI behaviors

- **Toasts** (AntD `message` via `App`): success/error for every mutation (create contact/template,
  edit, delete, send, login, register, reset) — non-blocking (FR-036).
- **Confirm** (AntD `Modal.confirm`): template delete requires explicit confirmation (FR-022).
- **Recipient picker**: AntD `Select mode="multiple"`, options from the user's contacts (fetched
  paged), searchable for large lists (FR-019).
- **Deep-link "recent window" indicator** on the dashboard when `capped` (FR-033).
- **Responsive**: AntD `Layout` + `Grid`; tables scroll-x on narrow widths (FR-038). Labeled fields,
  keyboard-navigable (AntD defaults), sufficient contrast.
