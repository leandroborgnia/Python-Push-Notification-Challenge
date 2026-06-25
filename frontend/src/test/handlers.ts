import { http, HttpResponse } from "msw";

import type { Contact, Dispatch, Template, TokenResponse } from "../api/types";

// Default happy-path handlers for the whole `/api/v1` surface the SPA consumes. A leading `*` makes
// each match any origin (the test base URL is http://api.localhost). Individual tests override the
// handler they care about via `server.use(...)` to drive errors, paging, or stateful behavior.
export const handlers = [
  // --- auth ---
  http.post("*/api/v1/auth/register", () =>
    HttpResponse.json({ status: "registered" }, { status: 201 }),
  ),
  http.post("*/api/v1/auth/verify", () => HttpResponse.json({ status: "verified" })),
  http.post("*/api/v1/auth/login", () =>
    HttpResponse.json<TokenResponse>({ access_token: "test-token", token_type: "bearer" }),
  ),
  http.get("*/api/v1/auth/me", () => HttpResponse.json({ user_id: "user-1" })),
  http.post("*/api/v1/auth/reset-request", () => new HttpResponse(null, { status: 202 })),
  http.post("*/api/v1/auth/reset-confirm", () => HttpResponse.json({ status: "password updated" })),

  // --- contacts ---
  http.get("*/api/v1/contacts", () => HttpResponse.json<Contact[]>([])),
  http.post("*/api/v1/contacts", async ({ request }) => {
    const body = (await request.json()) as Partial<Contact>;
    return HttpResponse.json<Contact>(
      {
        id: crypto.randomUUID(),
        display_name: body.display_name ?? "",
        email: body.email ?? null,
        phone: body.phone ?? null,
        device_token: body.device_token ?? null,
      },
      { status: 201 },
    );
  }),

  // --- templates ---
  http.get("*/api/v1/templates", () => HttpResponse.json<Template[]>([])),
  http.post("*/api/v1/templates", async ({ request }) => {
    const body = (await request.json()) as Omit<Template, "id">;
    return HttpResponse.json<Template>({ id: crypto.randomUUID(), ...body }, { status: 201 });
  }),
  http.put("*/api/v1/templates/:id", async ({ request, params }) => {
    const body = (await request.json()) as Omit<Template, "id">;
    return HttpResponse.json<Template>({ id: String(params.id), ...body });
  }),
  http.delete("*/api/v1/templates/:id", () => new HttpResponse(null, { status: 204 })),
  http.post("*/api/v1/templates/:id/send", () =>
    HttpResponse.json({ dispatch_id: crypto.randomUUID(), status: "accepted" }, { status: 202 }),
  ),

  // --- sends ---
  http.get("*/api/v1/sends", () => HttpResponse.json<Dispatch[]>([])),
  http.get("*/api/v1/sends/:id", ({ params }) =>
    HttpResponse.json<Dispatch>({
      dispatch_id: String(params.id),
      channel: "email",
      created_at: null,
      deliveries: [],
    }),
  ),
];
