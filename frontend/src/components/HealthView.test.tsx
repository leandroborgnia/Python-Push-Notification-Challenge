import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { HealthView } from "./HealthView";

const healthyReport = {
  status: "healthy",
  checked_at: "2026-06-20T00:00:00Z",
  checks: [
    { name: "data_store", passed: true, detail: null },
    { name: "message_broker", passed: true, detail: null },
    { name: "worker_pool_cpu", passed: true, detail: null },
    { name: "worker_pool_io", passed: true, detail: null },
  ],
};

afterEach(() => vi.restoreAllMocks());

test("renders healthy status and per-subsystem breakdown", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ status: 200, json: async () => healthyReport }),
  );
  render(<HealthView />);
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveAttribute("data-status", "healthy"),
  );
  expect(screen.getByText(/data_store: pass/)).toBeInTheDocument();
});

test("reflects a non-healthy verdict", async () => {
  const report = {
    ...healthyReport,
    status: "not_healthy",
    checks: [
      { name: "data_store", passed: false, detail: "down" },
      ...healthyReport.checks.slice(1),
    ],
  };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ status: 503, json: async () => report }));
  render(<HealthView />);
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveAttribute("data-status", "not_healthy"),
  );
});

test("shows unavailable on fetch failure", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));
  render(<HealthView />);
  await waitFor(() =>
    expect(screen.getByRole("status")).toHaveAttribute("data-status", "unavailable"),
  );
});
