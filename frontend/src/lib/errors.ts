// PURE error normalization (data-model R9, drives SC-004). The backend returns TWO body shapes:
//   - domain errors:            { detail: string }                         (400/403/404/409/422)
//   - FastAPI request-validation: { detail: [{ loc, msg, type }, ...] }     (422)
// This module turns either shape — plus network failures — into a single ApiError the UI can read.

export interface ApiError {
  status: number; // HTTP status (0 for a network/transport failure)
  detail: string; // human-facing message (server `detail` preferred when specific)
  fieldErrors?: Record<string, string>; // present when a FastAPI 422 validation array was returned
}

interface ValidationItem {
  loc?: unknown[];
  msg?: string;
}

// Default per-status messages when the server does not supply a more specific one.
const DEFAULTS: Record<number, string> = {
  401: "Your session expired. Please sign in.",
  403: "You don't have access to that.",
  404: "Not found or no longer available.",
  409: "That email is already registered.",
};

const NETWORK_MESSAGE = "Something went wrong. Please try again.";

/** The last segment of a FastAPI `loc` tuple is the offending field name (after "body"/"query"). */
function fieldName(loc: unknown[] | undefined): string {
  if (!loc || loc.length === 0) return "_";
  const last = loc[loc.length - 1];
  return typeof last === "string" || typeof last === "number" ? String(last) : "_";
}

/** Pull the `detail` field out of an arbitrary parsed body, if present. */
function extractDetail(body: unknown): string | ValidationItem[] | undefined {
  if (typeof body === "object" && body !== null && "detail" in body) {
    return (body as { detail?: string | ValidationItem[] }).detail;
  }
  return undefined;
}

/** Build an ApiError from an HTTP status and the parsed (or unparsable) response body. */
export function toApiError(status: number, body: unknown): ApiError {
  const detail = extractDetail(body);

  if (Array.isArray(detail)) {
    // FastAPI request-validation array → field-level messages + a readable summary.
    const fieldErrors: Record<string, string> = {};
    for (const item of detail) {
      const name = fieldName(item.loc);
      if (item.msg && !fieldErrors[name]) fieldErrors[name] = item.msg;
    }
    const summary = Object.values(fieldErrors)[0] ?? DEFAULTS[status] ?? "Please check the form.";
    return { status, detail: summary, fieldErrors };
  }

  if (typeof detail === "string" && detail.trim() !== "") {
    return { status, detail };
  }

  if (status >= 500) return { status, detail: NETWORK_MESSAGE };
  return { status, detail: DEFAULTS[status] ?? NETWORK_MESSAGE };
}

/** An ApiError for a transport failure (no HTTP response at all). */
export function networkError(): ApiError {
  return { status: 0, detail: NETWORK_MESSAGE };
}

/** Narrowing guard so callers (and tests) can treat thrown values as ApiError. */
export function isApiError(value: unknown): value is ApiError {
  return (
    typeof value === "object" &&
    value !== null &&
    "status" in value &&
    "detail" in value &&
    typeof (value as ApiError).detail === "string"
  );
}
