// PURE client-side validators mirroring the backend rules (data-model "Validation rules"). These are
// a fast-fail convenience only — the server stays the source of truth and every server rejection is
// surfaced even when these pass (FR-037).

export const SMS_MAX_LENGTH = 160;
export const MIN_PASSWORD_LENGTH = 8;

// Pragmatic email shape (the backend uses EmailStr; this just catches obvious typos before a round
// trip). Requires a local part, an "@", a dotted domain, and no whitespace.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isValidEmail(value: string): boolean {
  return EMAIL_RE.test(value.trim());
}

export function isNonEmpty(value: string | null | undefined): boolean {
  return typeof value === "string" && value.trim().length > 0;
}

export function isValidPassword(value: string): boolean {
  return value.length >= MIN_PASSWORD_LENGTH;
}

/** SMS bodies are capped at 160 characters (the single-segment limit). */
export function isWithinSmsLimit(content: string): boolean {
  return content.length <= SMS_MAX_LENGTH;
}

/** A contact needs a display name and at least one reachable destination (FR-016). */
export function hasAtLeastOneDestination(fields: {
  email?: string | null;
  phone?: string | null;
  device_token?: string | null;
}): boolean {
  return isNonEmpty(fields.email) || isNonEmpty(fields.phone) || isNonEmpty(fields.device_token);
}
