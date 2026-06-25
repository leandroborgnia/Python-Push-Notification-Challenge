# Contract: Typed API Client (`src/api/`)

The SPA's consumption contract for the existing `/api/v1` backend. Base URL = `VITE_API_BASE_URL`
(dev `http://api.localhost`). All authed calls send `Authorization: Bearer <token>`. The full backend
contract lives in [`specs/003-notification-management/contracts/notification-api.yaml`](../../003-notification-management/contracts/notification-api.yaml);
this file pins the client surface the SPA depends on. Cross-origin requires the CORS change in
[`backend-cors.md`](./backend-cors.md).

## Transport core — `http.ts`

```ts
// Single entry point used by all client modules and TanStack Query fns.
request<T>(method, path, opts?: {
  json?: unknown;             // JSON body (sets Content-Type: application/json)
  form?: Record<string,string>; // urlencoded body (login only)
  query?: Record<string, string | number>;
  auth?: boolean;             // attach Bearer (default true except auth endpoints)
}): Promise<T>
```

Responsibilities: prefix base URL; attach Bearer; serialize JSON/urlencoded; on non-2xx parse the
body and throw `ApiError` (normalize **both** `{detail:string}` and `{detail:[{loc,msg}]}`, per
data-model R9); on `401` clear session + call `onUnauthorized`; return parsed JSON (or `void` for 204).

## Client modules → endpoints

| Function | Method & path | Body / query | Returns | Notes |
|---|---|---|---|---|
| `auth.register(email, password)` | `POST /api/v1/auth/register` | json `{email,password}` | `{status}` | 201; 409 if email taken |
| `auth.verify(token)` | `POST /api/v1/auth/verify?token=…` | query `token` | `{status}` | 400 invalid/expired/used |
| `auth.login(email, password)` | `POST /api/v1/auth/login` | **form** `username=email,password` | `TokenResponse` | OAuth2 password; 400 bad creds / unverified |
| `auth.me()` | `GET /api/v1/auth/me` | — | `MeResponse` | token validity probe (returns `{user_id}` only) |
| `auth.requestReset(email)` | `POST /api/v1/auth/reset-request` | json `{email}` | `void` | always 202 (no enumeration) |
| `auth.confirmReset(token, newPassword)` | `POST /api/v1/auth/reset-confirm` | json `{token,new_password}` | `{status}` | 400 invalid/expired |
| `contacts.list(limit, offset)` | `GET /api/v1/contacts` | query `limit≤100,offset` | `Contact[]` | paged |
| `contacts.create(body)` | `POST /api/v1/contacts` | json `ContactCreate` | `Contact` | 422 if no destination |
| `templates.list(limit, offset)` | `GET /api/v1/templates` | query `limit≤100,offset` | `Template[]` | paged |
| `templates.create(body)` | `POST /api/v1/templates` | json `TemplateCreate` | `Template` | 422 SMS>160 / unknown channel / recipient not owned |
| `templates.update(id, body)` | `PUT /api/v1/templates/{id}` | json `TemplateCreate` | `Template` | 404 not owned; 422 validation; never sends |
| `templates.remove(id)` | `DELETE /api/v1/templates/{id}` | — | `void` | 204; 404 not owned |
| `templates.send(id)` | `POST /api/v1/templates/{id}/send` | — | `DispatchAck` | 202; 400 unsendable; 404 not owned |
| `sends.list(limit, offset)` | `GET /api/v1/sends` | query `limit≤100,offset` | `Dispatch[]` | full transitions per delivery |
| `sends.get(id)` | `GET /api/v1/sends/{id}` | — | `Dispatch` | 404 not owned |

## TanStack Query usage

| Key | Source | Refetch |
|---|---|---|
| `['contacts']` | `contacts.list` (paged for table + picker) | invalidate after `contacts.create` (FR-017) |
| `['templates']` | `templates.list` | invalidate after create/update/remove |
| `['sends']` | `sends.list` | `refetchInterval` 4s while any delivery non-terminal; manual refresh = invalidate (R8) |
| `['send', id]` | `sends.get` | same polling rule while open in the detail drawer |
| `['dashboard']` | `lib/aggregate` over paged `sends.list` (cap 2000) | manual refresh only (FR-034) |

Mutations: `templates.send` → on success show "Accepted for delivery" toast (≤2s, SC-010) and
invalidate `['sends']`. `retry: false` for 4xx (don't retry validation/auth failures); the dual error
shape is mapped once in `http.ts`, so components read `ApiError.detail` / `ApiError.fieldErrors`.

## Auth-page specifics

- Login uses the **urlencoded** form body (`username`/`password`) — not JSON. Persist
  `{token, email}` to the session on success.
- Unverified-login (400) → surface server `detail` and reveal the **Verify** mode (FR-012).
- `/verify` and `/reset` landing routes pull `token` from the query and call `auth.verify` /
  `auth.confirmReset` (auto for verify; on submit for reset).
