import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "../../test/renderWithProviders";
import { server } from "../../test/server";
import { AuthPage } from "./AuthPage";

function renderAt(entry: string) {
  return renderWithProviders(<AuthPage />, { initialEntries: [entry] });
}

describe("AuthPage", () => {
  it("defaults to the Login mode", () => {
    renderAt("/auth");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });

  it("switches modes in place", async () => {
    const user = userEvent.setup();
    renderAt("/auth");

    await user.click(screen.getByRole("button", { name: "Register" }));
    expect(screen.getByRole("button", { name: "Create account" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Back to sign in/i }));
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(screen.getByLabelText("Token")).toBeInTheDocument();
  });

  it("guides the user to verify after registering", async () => {
    const user = userEvent.setup();
    renderAt("/auth");

    await user.click(screen.getByRole("button", { name: "Register" }));
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "correct horse");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(
      await screen.findByText(/sent a verification link to ada@example.com/i),
    ).toBeInTheDocument();
  });

  it("auto-verifies from a /verify?token= deep link", async () => {
    renderAt("/verify?token=good-token");
    expect(await screen.findByText(/Email verified/i)).toBeInTheDocument();
  });

  it("reports a specific failure for an invalid verification token", async () => {
    server.use(
      http.post("*/api/v1/auth/verify", () =>
        HttpResponse.json({ detail: "Invalid or expired token" }, { status: 400 }),
      ),
    );
    renderAt("/verify?token=bad-token");
    expect(await screen.findByText(/Invalid or expired token/i)).toBeInTheDocument();
  });

  it("surfaces an unverified-login message and reveals the Verify path", async () => {
    server.use(
      http.post("*/api/v1/auth/login", () =>
        HttpResponse.json({ detail: "Account is not verified" }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderAt("/auth");

    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "correct horse");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText(/not verified/i)).toBeInTheDocument();
    expect(await screen.findByLabelText("Token")).toBeInTheDocument();
  });

  it("always acknowledges a reset request, even on a server error", async () => {
    server.use(
      http.post("*/api/v1/auth/reset-request", () => new HttpResponse(null, { status: 500 })),
    );
    const user = userEvent.setup();
    renderAt("/auth");

    await user.click(screen.getByRole("button", { name: /Reset it/i }));
    await user.type(screen.getByLabelText("Email"), "ghost@example.com");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));

    expect(await screen.findByText(/reset link is on its way/i)).toBeInTheDocument();
  });

  it("directs the user to sign in after confirming a reset from a /reset deep link", async () => {
    const user = userEvent.setup();
    renderAt("/reset?token=reset-token");

    // Token is prefilled from the deep link; just set a new password.
    await user.type(screen.getByLabelText("New password"), "brand new pass");
    await user.click(screen.getByRole("button", { name: "Update password" }));

    expect(await screen.findByText(/Password updated/i)).toBeInTheDocument();
  });
});
