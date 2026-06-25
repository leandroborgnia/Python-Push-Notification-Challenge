import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { Contact, ContactCreate } from "../../api/types";
import { renderWithProviders } from "../../test/renderWithProviders";
import { server } from "../../test/server";
import { ContactsPage } from "./ContactsPage";

function makeContact(body: ContactCreate): Contact {
  return {
    id: crypto.randomUUID(),
    display_name: body.display_name,
    email: body.email ?? null,
    phone: body.phone ?? null,
    device_token: body.device_token ?? null,
  };
}

describe("ContactsPage", () => {
  it("shows the empty state when there are no contacts", async () => {
    renderWithProviders(<ContactsPage />);
    expect(await screen.findByText(/No contacts yet/i)).toBeInTheDocument();
  });

  it("creates a contact and it appears without a manual reload", async () => {
    const store: Contact[] = [];
    server.use(
      http.get("*/api/v1/contacts", () => HttpResponse.json(store)),
      http.post("*/api/v1/contacts", async ({ request }) => {
        const created = makeContact((await request.json()) as ContactCreate);
        store.push(created);
        return HttpResponse.json(created, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<ContactsPage />);

    await screen.findByText(/No contacts yet/i);
    await user.type(screen.getByLabelText("Display name"), "Ada Lovelace");
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.click(screen.getByRole("button", { name: /add contact/i }));

    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
  });

  it("blocks a submission with no destination, client-side", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ContactsPage />);

    await screen.findByText(/No contacts yet/i);
    await user.type(screen.getByLabelText("Display name"), "No Destinations");
    await user.click(screen.getByRole("button", { name: /add contact/i }));

    expect(await screen.findByText(/at least one destination/i)).toBeInTheDocument();
  });

  it("pages through when there is more than one page of contacts", async () => {
    const all: Contact[] = Array.from({ length: 12 }, (_, i) => ({
      id: `id-${i}`,
      display_name: `Contact ${i + 1}`,
      email: null,
      phone: `555-00${i}`,
      device_token: null,
    }));
    server.use(
      http.get("*/api/v1/contacts", ({ request }) => {
        const url = new URL(request.url);
        const limit = Number(url.searchParams.get("limit") ?? "10");
        const offset = Number(url.searchParams.get("offset") ?? "0");
        return HttpResponse.json(all.slice(offset, offset + limit));
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<ContactsPage />);

    expect(await screen.findByText("Contact 1")).toBeInTheDocument();
    expect(screen.queryByText("Contact 11")).not.toBeInTheDocument();

    await user.click(screen.getByTitle("2"));
    expect(await screen.findByText("Contact 11")).toBeInTheDocument();
  });
});
