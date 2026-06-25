import { describe, expect, it } from "vitest";

import { isApiError, networkError, toApiError } from "./errors";

describe("toApiError", () => {
  it("uses the server detail string for domain errors", () => {
    const err = toApiError(400, { detail: "Account not verified" });
    expect(err).toEqual({ status: 400, detail: "Account not verified" });
    expect(err.fieldErrors).toBeUndefined();
  });

  it("maps a FastAPI 422 validation array into fieldErrors + a summary", () => {
    const err = toApiError(422, {
      detail: [
        { loc: ["body", "email"], msg: "value is not a valid email address", type: "value_error" },
        { loc: ["body", "password"], msg: "String should have at least 8 characters" },
      ],
    });
    expect(err.status).toBe(422);
    expect(err.fieldErrors).toEqual({
      email: "value is not a valid email address",
      password: "String should have at least 8 characters",
    });
    // The summary is the first field message so a form-level alert is still meaningful.
    expect(err.detail).toBe("value is not a valid email address");
  });

  it("handles a 422 domain error delivered as a plain string", () => {
    const err = toApiError(422, { detail: "SMS content exceeds 160 characters" });
    expect(err.detail).toBe("SMS content exceeds 160 characters");
    expect(err.fieldErrors).toBeUndefined();
  });

  it("falls back to per-status defaults when no detail is given", () => {
    expect(toApiError(401, null).detail).toMatch(/session expired/i);
    expect(toApiError(403, {}).detail).toMatch(/access/i);
    expect(toApiError(404, undefined).detail).toMatch(/not found/i);
    expect(toApiError(409, {}).detail).toMatch(/already registered/i);
  });

  it("maps 5xx and unknown statuses to a generic retry message", () => {
    expect(toApiError(500, null).detail).toMatch(/something went wrong/i);
    expect(toApiError(503, "<html>").detail).toMatch(/something went wrong/i);
  });

  it("prefers a specific server detail over the default even on 409", () => {
    expect(toApiError(409, { detail: "Email taken: ada@x.com" }).detail).toBe(
      "Email taken: ada@x.com",
    );
  });
});

describe("networkError", () => {
  it("is a status-0 ApiError with the generic message", () => {
    const err = networkError();
    expect(err.status).toBe(0);
    expect(err.detail).toMatch(/something went wrong/i);
  });
});

describe("isApiError", () => {
  it("recognizes ApiError-shaped values and rejects others", () => {
    expect(isApiError(toApiError(404, null))).toBe(true);
    expect(isApiError(new Error("boom"))).toBe(false);
    expect(isApiError(null)).toBe(false);
    expect(isApiError({ status: 1 })).toBe(false);
  });
});
