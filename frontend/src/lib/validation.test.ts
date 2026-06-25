import { describe, expect, it } from "vitest";

import {
  hasAtLeastOneDestination,
  isNonEmpty,
  isValidEmail,
  isValidPassword,
  isWithinSmsLimit,
  SMS_MAX_LENGTH,
} from "./validation";

describe("isValidEmail", () => {
  it("accepts well-formed addresses", () => {
    expect(isValidEmail("ada@example.com")).toBe(true);
    expect(isValidEmail("  ada.lovelace@sub.example.co  ")).toBe(true);
  });

  it("rejects malformed addresses", () => {
    expect(isValidEmail("ada@")).toBe(false);
    expect(isValidEmail("ada@example")).toBe(false);
    expect(isValidEmail("ada example.com")).toBe(false);
    expect(isValidEmail("")).toBe(false);
  });
});

describe("isNonEmpty", () => {
  it("treats whitespace-only and nullish as empty", () => {
    expect(isNonEmpty("x")).toBe(true);
    expect(isNonEmpty("   ")).toBe(false);
    expect(isNonEmpty("")).toBe(false);
    expect(isNonEmpty(null)).toBe(false);
    expect(isNonEmpty(undefined)).toBe(false);
  });
});

describe("isValidPassword", () => {
  it("enforces the 8-character minimum at the boundary", () => {
    expect(isValidPassword("1234567")).toBe(false);
    expect(isValidPassword("12345678")).toBe(true);
  });
});

describe("isWithinSmsLimit", () => {
  it("allows exactly 160 characters and rejects 161", () => {
    expect(isWithinSmsLimit("a".repeat(SMS_MAX_LENGTH))).toBe(true);
    expect(isWithinSmsLimit("a".repeat(SMS_MAX_LENGTH + 1))).toBe(false);
    expect(isWithinSmsLimit("")).toBe(true);
  });
});

describe("hasAtLeastOneDestination", () => {
  it("requires at least one of email/phone/device_token", () => {
    expect(hasAtLeastOneDestination({})).toBe(false);
    expect(hasAtLeastOneDestination({ email: "", phone: "  ", device_token: null })).toBe(false);
    expect(hasAtLeastOneDestination({ email: "ada@x.com" })).toBe(true);
    expect(hasAtLeastOneDestination({ phone: "+15551234567" })).toBe(true);
    expect(hasAtLeastOneDestination({ device_token: "tok" })).toBe(true);
  });
});
