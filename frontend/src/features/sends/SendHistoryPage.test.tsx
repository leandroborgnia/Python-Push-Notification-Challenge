import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { DeliveryState, Dispatch, Template } from "../../api/types";
import { renderWithProviders } from "../../test/renderWithProviders";
import { server } from "../../test/server";
import { SendHistoryPage } from "./SendHistoryPage";

const TEMPLATE: Template = {
  id: "t1",
  title: "Welcome",
  content: "Hi",
  channel: "email",
  recipient_contact_ids: ["c1"],
};

function dispatchWith(status: DeliveryState): Dispatch {
  return {
    dispatch_id: "d1",
    channel: "email",
    created_at: "2026-06-24T10:00:00Z",
    deliveries: [
      {
        delivery_id: "del1",
        recipient_name: "Ada",
        destination: "ada@example.com",
        status,
        failure_reason: null,
        transitions: [
          {
            from_status: null,
            to_status: "queued",
            reason: null,
            attempt: null,
            at: "2026-06-24T10:00:00Z",
          },
          {
            from_status: "queued",
            to_status: "sent",
            reason: null,
            attempt: 1,
            at: "2026-06-24T10:00:05Z",
          },
          ...(status === "delivered"
            ? [
                {
                  from_status: "sent" as const,
                  to_status: "delivered" as const,
                  reason: null,
                  attempt: 1,
                  at: "2026-06-24T10:00:10Z",
                },
              ]
            : []),
        ],
      },
    ],
  };
}

describe("SendHistoryPage", () => {
  it("sends the selected template and shows an acceptance toast", async () => {
    server.use(
      http.get("*/api/v1/templates", () => HttpResponse.json([TEMPLATE])),
      http.get("*/api/v1/sends", () => HttpResponse.json([])),
    );
    const user = userEvent.setup();
    renderWithProviders(<SendHistoryPage />);

    await screen.findByText(/No sends yet/i);
    await user.click(screen.getByRole("combobox"));
    await user.click(await screen.findByText(/Welcome \(email\)/));
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText(/Accepted for delivery/i)).toBeInTheDocument();
  });

  it("surfaces an unsendable 400 and adds no history entry", async () => {
    server.use(
      http.get("*/api/v1/templates", () => HttpResponse.json([TEMPLATE])),
      http.get("*/api/v1/sends", () => HttpResponse.json([])),
      http.post("*/api/v1/templates/:id/send", () =>
        HttpResponse.json({ detail: "Template has no recipients" }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<SendHistoryPage />);

    await screen.findByText(/No sends yet/i);
    await user.click(screen.getByRole("combobox"));
    await user.click(await screen.findByText(/Welcome \(email\)/));
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText(/no recipients/i)).toBeInTheDocument();
    expect(screen.getByText(/No sends yet/i)).toBeInTheDocument(); // no spurious entry
  });

  it("lists backend sends and opens a per-recipient detail with the transition timeline", async () => {
    const dispatch = dispatchWith("delivered");
    server.use(
      http.get("*/api/v1/templates", () => HttpResponse.json([])),
      http.get("*/api/v1/sends", () => HttpResponse.json([dispatch])),
      http.get("*/api/v1/sends/:id", () => HttpResponse.json(dispatch)),
    );
    const user = userEvent.setup();
    renderWithProviders(<SendHistoryPage />);

    const statusTag = await screen.findByText(/1 delivered/i);
    await user.click(statusTag);

    expect(await screen.findByText("Ada")).toBeInTheDocument();
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    // The transition timeline renders each step as "from → to" inside a <strong>.
    expect(
      await screen.findByText(
        (_content, el) => el?.tagName === "STRONG" && el.textContent === "sent → delivered",
      ),
    ).toBeInTheDocument();
  });

  it("advances delivery status by polling, without a page reload", async () => {
    let calls = 0;
    server.use(
      http.get("*/api/v1/templates", () => HttpResponse.json([])),
      http.get("*/api/v1/sends", () => {
        calls += 1;
        return HttpResponse.json([dispatchWith(calls === 1 ? "queued" : "delivered")]);
      }),
    );
    renderWithProviders(<SendHistoryPage />);

    // Initial load shows the in-progress status…
    expect(await screen.findByText(/1 queued/i)).toBeInTheDocument();
    // …and the 4s poll advances it to a terminal state in place (no reload, no extra interaction).
    expect(
      await screen.findByText(/1 delivered/i, undefined, { timeout: 6000 }),
    ).toBeInTheDocument();
  }, 10000);
});
