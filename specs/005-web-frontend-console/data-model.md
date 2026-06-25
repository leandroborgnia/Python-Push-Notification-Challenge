# Data Model: Enterprise Admin Web Frontend

Client-side types and rules. These mirror the backend schemas (`backend/app/api/schemas.py`) — the
backend remains the source of truth; the SPA never invents fields. No new persistent storage is
introduced (the only persisted client state is the session in `localStorage`).

## DTOs (wire types — mirror `/api/v1`)

```ts
// api/types.ts
export type Channel = 'email' | 'sms' | 'push';
export type DeliveryState = 'queued' | 'sent' | 'delivered' | 'failed';

export interface TokenResponse { access_token: string; token_type: 'bearer'; }
export interface MeResponse { user_id: string; }

export interface Contact {
  id: string;                 // uuid
  display_name: string;
  email: string | null;
  phone: string | null;
  device_token: string | null;
}
export interface ContactCreate {
  display_name: string;
  email?: string | null;
  phone?: string | null;
  device_token?: string | null;
}

export interface Template {
  id: string;                 // uuid
  title: string;
  content: string;
  channel: Channel;
  recipient_contact_ids: string[];
}
export type TemplateCreate = Omit<Template, 'id'>;  // also the PUT body

export interface DispatchAck { dispatch_id: string; status: 'accepted'; }

export interface Transition {
  from_status: DeliveryState | null;
  to_status: DeliveryState;
  reason: string | null;
  attempt: number | null;
  at: string | null;          // ISO-8601 UTC; null only in degenerate cases
}
export interface Delivery {
  delivery_id: string;
  recipient_name: string;
  destination: string | null;
  status: DeliveryState;
  failure_reason: string | null;
  transitions: Transition[];
}
export interface Dispatch {
  dispatch_id: string;
  channel: Channel;
  created_at: string | null;  // ISO-8601 UTC
  deliveries: Delivery[];
}
```

> Note: `GET /sends` returns `Dispatch[]` with **full** per-delivery `transitions` — the dashboard
> aggregates straight from list pages (no `/sends/{id}` fan-out needed).

## Client-only view models

```ts
// auth/session.ts
export interface Session { token: string; email: string; }   // persisted in localStorage 'nsvc.session'

// api/http.ts
export interface ApiError {
  status: number;                       // HTTP status
  detail: string;                       // human-facing message (from server or mapped default)
  fieldErrors?: Record<string, string>; // present when FastAPI returned a 422 validation array
}

// lib/aggregate.ts
export interface HourAggregate {
  buckets: number[];          // length 24, index = UTC hour 00..23
  totalSent: number;          // sum of buckets
  dispatchesScanned: number;
  mostRecentSentAt: string | null;
  capped: boolean;            // true if the scan stopped at the cap (recent-window, not all-time)
}
```

## Entities & relationships

- **Session** — `{ token, email }`. Created by login; cleared by logout or any 401. Drives routing
  (present ⇒ shell, absent ⇒ `/auth`) and the app-bar identity.
- **Contact** *owned by the user* — display name + ≥1 destination. Create + list only (no edit/delete).
- **Template** *owned by the user* — title, content, one `channel`, and `recipient_contact_ids`
  referencing the user's own **Contacts**. Create/edit/delete; sending is a separate action.
- **Dispatch (Send)** — one send of a template: a `channel`, `created_at`, and 1..N **Deliveries**.
- **Delivery** — one recipient's outcome: current `status`, `destination`, optional `failure_reason`,
  and an append-only `transitions[]` history.
- **HourAggregate** — derived from the user's **Dispatch** list; not persisted.

```
Session ──auth──> [Contacts] ──referenced by──> [Templates] ──send──> [Dispatches] ──> [Deliveries] ──> [Transitions]
                                                                              └────────► HourAggregate (derived, client-side)
```

## Validation rules (client mirrors backend; server is source of truth — FR-037)

| Field / form | Client rule | Backend behavior on violation |
|---|---|---|
| Register / Reset password | length ≥ 8 | FastAPI 422 `{detail:[…]}` |
| Email (register, reset-request, contact email) | RFC-ish email format | FastAPI 422 (EmailStr) `{detail:[…]}` |
| Contact | `display_name` required **and** ≥1 of email/phone/device_token | domain 422 `{detail:"…"}` |
| Template (SMS) | `content.length ≤ 160` | domain 422 `{detail:"…"}` |
| Template | `title`, `content`, `channel` required; ≥1 recipient; recipients owned by caller | domain 422 `{detail:"…"}` |
| Login | email + password present | bad creds / unverified ⇒ domain 400 `{detail:"…"}` |

Client validation is a fast-fail convenience; **every** server rejection is surfaced even when client
checks passed (R9). Recipient ownership and any rule the client cannot know are enforced only server-
side and surfaced from the response.

## Delivery lifecycle (display only — not enforced here)

`queued → sent → delivered | failed` (append-only transitions, defined by the backend). The SPA:
- renders the current `status` (AntD `Tag`/`Badge` with per-state color),
- renders the full `transitions[]` timeline in the send detail (from→to, reason, attempt, `at`),
- treats `delivered`/`failed` as **terminal** for polling (stop) and `queued`/`sent` as in-progress.

## Error-status → message mapping (R9; drives SC-004)

| Status | Source shape | Default user message (server `detail` preferred when specific) |
|---|---|---|
| 400 | `{detail:string}` | the server `detail` (e.g., bad credentials / unverified ⇒ also offer Verify) |
| 401 | (any) | session cleared → redirect to `/auth` ("Your session expired. Please sign in.") |
| 403 | `{detail:string}` | "You don't have access to that." |
| 404 | `{detail:string}` | "Not found or no longer available." |
| 409 | `{detail:string}` | "That email is already registered." |
| 422 | `{detail:string}` *or* `{detail:[{loc,msg}]}` | field-level messages (array) or the domain message (string) |
| 5xx / network | — | "Something went wrong. Please try again." + retry affordance |
