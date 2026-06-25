import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { Dispatch, Transition } from "../../api/types";
import { renderWithProviders } from "../../test/renderWithProviders";
import { server } from "../../test/server";
import { Dashboard } from "./Dashboard";

const sentAt = (at: string): Transition => ({
  from_status: "queued",
  to_status: "sent",
  reason: null,
  attempt: 1,
  at,
});

function dispatchWithSends(count: number, hourIso = "2026-06-24T09:00:00Z"): Dispatch {
  return {
    dispatch_id: crypto.randomUUID(),
    channel: "email",
    created_at: hourIso,
    deliveries: Array.from({ length: count }, (_, i) => ({
      delivery_id: `del-${i}`,
      recipient_name: `R${i}`,
      destination: null,
      status: "sent",
      failure_reason: null,
      transitions: [sentAt(hourIso)],
    })),
  };
}

function statValue(title: string): HTMLElement {
  const card = screen.getByText(title).closest(".ant-statistic") as HTMLElement;
  return card;
}

describe("Dashboard", () => {
  it("shows a sent total equal to an independent count of sent transitions", async () => {
    // Two dispatches: 2 + 1 = 3 sent transitions, counted independently of the SUT's aggregate().
    const dispatches = [dispatchWithSends(2), dispatchWithSends(1)];
    const independentSentCount = dispatches
      .flatMap((d) => d.deliveries)
      .flatMap((del) => del.transitions)
      .filter((t) => t.to_status === "sent").length;

    server.use(http.get("*/api/v1/sends", () => HttpResponse.json(dispatches)));
    renderWithProviders(<Dashboard />);

    await waitFor(() =>
      expect(within(statValue("Messages sent")).getByText(String(independentSentCount))),
    );
    expect(independentSentCount).toBe(3);
  });

  it("shows the empty state when there are no qualifying sends", async () => {
    server.use(http.get("*/api/v1/sends", () => HttpResponse.json([])));
    renderWithProviders(<Dashboard />);
    expect(await screen.findByText(/No sends yet/i)).toBeInTheDocument();
  });

  it("shows the recent-window indicator when the scan hits the cap", async () => {
    server.use(
      http.get("*/api/v1/sends", ({ request }) => {
        const offset = Number(new URL(request.url).searchParams.get("offset") ?? "0");
        // Always a full page → the scan stops at the 2,000-dispatch cap (capped=true).
        return HttpResponse.json(
          Array.from({ length: 100 }, (_, i) => ({
            dispatch_id: `d-${offset + i}`,
            channel: "email" as const,
            created_at: null,
            deliveries: [],
          })),
        );
      }),
    );
    renderWithProviders(<Dashboard />);
    expect(await screen.findByText(/Recent window/i)).toBeInTheDocument();
  });

  it("re-aggregates on Refresh", async () => {
    let calls = 0;
    server.use(
      http.get("*/api/v1/sends", () => {
        calls += 1;
        return HttpResponse.json(calls === 1 ? [dispatchWithSends(1)] : [dispatchWithSends(2)]);
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<Dashboard />);

    await waitFor(() =>
      expect(within(statValue("Messages sent")).getByText("1")).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: "Refresh" }));

    await waitFor(() =>
      expect(within(statValue("Messages sent")).getByText("2")).toBeInTheDocument(),
    );
  });
});
