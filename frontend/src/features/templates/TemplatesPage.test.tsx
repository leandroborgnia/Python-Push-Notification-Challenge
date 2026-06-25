import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import type { Contact, Template, TemplateCreate } from "../../api/types";
import { renderWithProviders } from "../../test/renderWithProviders";
import { server } from "../../test/server";
import { TemplatesPage } from "./TemplatesPage";

const ADA: Contact = {
  id: "c1",
  display_name: "Ada",
  email: "ada@example.com",
  phone: null,
  device_token: null,
};

function templateStore(initial: Template[] = []) {
  const store = [...initial];
  let sendCalled = false;
  const handlers = [
    http.get("*/api/v1/contacts", () => HttpResponse.json([ADA])),
    http.get("*/api/v1/templates", ({ request }) => {
      const url = new URL(request.url);
      const limit = Number(url.searchParams.get("limit") ?? "10");
      const offset = Number(url.searchParams.get("offset") ?? "0");
      return HttpResponse.json(store.slice(offset, offset + limit));
    }),
    http.post("*/api/v1/templates", async ({ request }) => {
      const body = (await request.json()) as TemplateCreate;
      const created: Template = { id: crypto.randomUUID(), ...body };
      store.push(created);
      return HttpResponse.json(created, { status: 201 });
    }),
    http.put("*/api/v1/templates/:id", async ({ request, params }) => {
      const body = (await request.json()) as TemplateCreate;
      const updated: Template = { id: String(params.id), ...body };
      const idx = store.findIndex((t) => t.id === params.id);
      if (idx >= 0) store[idx] = updated;
      return HttpResponse.json(updated);
    }),
    http.delete("*/api/v1/templates/:id", ({ params }) => {
      const idx = store.findIndex((t) => t.id === params.id);
      if (idx >= 0) store.splice(idx, 1);
      return new HttpResponse(null, { status: 204 });
    }),
    http.post("*/api/v1/templates/:id/send", () => {
      sendCalled = true;
      return HttpResponse.json({ dispatch_id: "d1", status: "accepted" }, { status: 202 });
    }),
  ];
  return { store, handlers, wasSendCalled: () => sendCalled };
}

beforeEach(() => {
  // A stored session so the authed list calls carry a token (handlers don't check it, but it mirrors
  // the running app).
  localStorage.setItem("nsvc.session", JSON.stringify({ token: "t", email: "ada@example.com" }));
});

// Open the AntD Select inside the form item carrying `labelText` (its label isn't a queryable form
// control, and the placeholder has pointer-events: none, so click the selector directly).
async function openSelect(
  user: ReturnType<typeof userEvent.setup>,
  labelText: string,
): Promise<void> {
  const item = screen.getByText(labelText).closest(".ant-form-item");
  const selector = item?.querySelector(".ant-select-selector");
  await user.click(selector as Element);
}

describe("TemplatesPage", () => {
  it("creates a template with a channel and recipients, listing only the user's contacts", async () => {
    const { handlers } = templateStore();
    server.use(...handlers);
    const user = userEvent.setup();
    renderWithProviders(<TemplatesPage />);

    await screen.findByText(/No templates yet/i);
    await user.click(screen.getByRole("button", { name: "New template" }));

    await user.type(screen.getByLabelText("Title"), "Welcome");
    await user.type(screen.getByLabelText("Content"), "Hello there");

    // The recipient picker is sourced only from the user's contacts.
    await openSelect(user, "Recipients");
    const option = await screen.findByText(/Ada \(ada@example\.com\)/);
    await user.click(option);

    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Welcome")).toBeInTheDocument();
  });

  it("blocks an SMS template whose content exceeds 160 characters, client-side", async () => {
    const { handlers } = templateStore();
    server.use(...handlers);
    const user = userEvent.setup();
    renderWithProviders(<TemplatesPage />);

    await screen.findByText(/No templates yet/i);
    await user.click(screen.getByRole("button", { name: "New template" }));
    await user.type(screen.getByLabelText("Title"), "Long SMS");

    // Switch the channel to SMS.
    await openSelect(user, "Channel");
    await user.click(await screen.findByText("SMS"));

    // Paste (not type) the long body — typing 161 chars one-by-one is far too slow under AntD.
    const content = screen.getByLabelText("Content");
    await user.click(content);
    await user.paste("a".repeat(161));
    await openSelect(user, "Recipients");
    await user.click(await screen.findByText(/Ada/));
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText(/limited to 160 characters/i)).toBeInTheDocument();
  });

  it("surfaces a server 422 for a recipient not owned by the caller", async () => {
    const { handlers } = templateStore();
    // The override must precede the store's POST handler so it wins (earlier = higher priority).
    server.use(
      http.post("*/api/v1/templates", () =>
        HttpResponse.json({ detail: "Recipient not owned by caller" }, { status: 422 }),
      ),
      ...handlers,
    );
    const user = userEvent.setup();
    renderWithProviders(<TemplatesPage />);

    await screen.findByText(/No templates yet/i);
    await user.click(screen.getByRole("button", { name: "New template" }));
    await user.type(screen.getByLabelText("Title"), "Bad recipient");
    await user.type(screen.getByLabelText("Content"), "Hello");
    await openSelect(user, "Recipients");
    await user.click(await screen.findByText(/Ada/));
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText(/Recipient not owned by caller/i)).toBeInTheDocument();
  });

  it("edits a selected template and saves it without sending", async () => {
    const existing: Template = {
      id: "t1",
      title: "Original",
      content: "Body",
      channel: "email",
      recipient_contact_ids: ["c1"],
    };
    const { handlers, wasSendCalled } = templateStore([existing]);
    server.use(...handlers);
    const user = userEvent.setup();
    renderWithProviders(<TemplatesPage />);

    await screen.findByText("Original");
    await user.click(screen.getByRole("radio")); // single-row selection
    await user.click(screen.getByRole("button", { name: "Edit" }));

    const title = screen.getByLabelText("Title");
    await user.clear(title);
    await user.type(title, "Renamed");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Renamed")).toBeInTheDocument();
    expect(wasSendCalled()).toBe(false);
  });

  it("requires confirmation to delete and never sends", async () => {
    const existing: Template = {
      id: "t1",
      title: "Doomed",
      content: "Body",
      channel: "email",
      recipient_contact_ids: ["c1"],
    };
    const { handlers, wasSendCalled } = templateStore([existing]);
    server.use(...handlers);
    const user = userEvent.setup();
    renderWithProviders(<TemplatesPage />);

    await screen.findByText("Doomed");
    await user.click(screen.getByRole("radio"));
    await user.click(screen.getByRole("button", { name: "Delete" }));

    // Confirmation dialog appears; confirm it.
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/permanently removed/i)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(screen.queryByText("Doomed")).not.toBeInTheDocument());
    expect(wasSendCalled()).toBe(false);
  });
});
