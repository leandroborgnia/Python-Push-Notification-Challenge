import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App as AntApp, ConfigProvider } from "antd";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { contacts } from "../api/contacts";
import { AuthPage } from "../features/auth/AuthPage";
import { server } from "../test/server";
import { AuthProvider } from "./AuthProvider";
import { loadSession, saveSession } from "./session";

// A button that fires an authenticated request; a 401 from it should clear the session globally.
function ProbeButton() {
  return <button onClick={() => void contacts.list().catch(() => undefined)}>probe</button>;
}

function renderTree() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ConfigProvider>
        <AntApp>
          <MemoryRouter initialEntries={["/"]}>
            <AuthProvider>
              <Routes>
                <Route path="/" element={<ProbeButton />} />
                <Route path="/auth" element={<AuthPage />} />
              </Routes>
            </AuthProvider>
          </MemoryRouter>
        </AntApp>
      </ConfigProvider>
    </QueryClientProvider>,
  );
}

describe("AuthProvider", () => {
  it("clears the session and redirects to /auth when an authed call returns 401", async () => {
    saveSession({ token: "stale", email: "ada@example.com" });
    // The on-load /me probe succeeds; the later contacts call is the one that 401s.
    server.use(
      http.get("*/api/v1/contacts", () =>
        HttpResponse.json({ detail: "expired" }, { status: 401 }),
      ),
    );
    const user = userEvent.setup();
    renderTree();

    await user.click(await screen.findByRole("button", { name: "probe" }));

    expect(await screen.findByText(/session expired/i)).toBeInTheDocument();
    expect(loadSession()).toBeNull();
  });

  it("clears a stale stored session when the on-load /me probe returns 401", async () => {
    saveSession({ token: "stale", email: "ada@example.com" });
    server.use(
      http.get("*/api/v1/auth/me", () => HttpResponse.json({ detail: "expired" }, { status: 401 })),
    );
    renderTree();

    // The probe 401 routes to /auth; the login form (Sign in button) is now showing.
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(loadSession()).toBeNull();
  });
});
