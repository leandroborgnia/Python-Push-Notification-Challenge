// Transport core: the single fetch entry point used by every client module and TanStack Query fn.
// Responsibilities: prefix the API base URL, attach the Bearer token, serialize JSON/urlencoded
// bodies, normalize non-2xx responses into ApiError (both backend shapes), and on any 401 clear the
// session and invoke the registered onUnauthorized handler (FR-005). See contracts/api-client.md.

import { clearSession, loadSession } from "../auth/session";
import { networkError, toApiError } from "../lib/errors";

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

type UnauthorizedHandler = () => void;
let onUnauthorized: UnauthorizedHandler | null = null;

/** AuthProvider registers a callback here so a 401 anywhere routes back to /auth. */
export function registerUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  onUnauthorized = handler;
}

export interface RequestOptions {
  json?: unknown; // JSON body (sets Content-Type: application/json)
  form?: Record<string, string>; // urlencoded body (login only)
  query?: Record<string, string | number>;
  auth?: boolean; // attach Bearer (default true)
}

function buildUrl(path: string, query?: Record<string, string | number>): string {
  const url = `${BASE_URL}${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) params.set(key, String(value));
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

export async function request<T>(
  method: string,
  path: string,
  opts: RequestOptions = {},
): Promise<T> {
  const { json, form, query, auth = true } = opts;
  const headers: Record<string, string> = {};
  let body: BodyInit | undefined;

  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (form !== undefined) {
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    body = new URLSearchParams(form).toString();
  }

  if (auth) {
    const session = loadSession();
    if (session) headers["Authorization"] = `Bearer ${session.token}`;
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), { method, headers, body });
  } catch {
    throw networkError();
  }

  if (response.status === 401) {
    clearSession();
    onUnauthorized?.();
  }

  if (!response.ok) {
    let parsed: unknown = null;
    try {
      parsed = await response.json();
    } catch {
      parsed = null;
    }
    throw toApiError(response.status, parsed);
  }

  if (response.status === 204) return undefined as T;
  const text = await response.text();
  if (text === "") return undefined as T; // e.g. reset-request 202 with no body
  return JSON.parse(text) as T;
}

export const httpClient = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>("GET", path, opts),
  post: <T>(path: string, opts?: RequestOptions) => request<T>("POST", path, opts),
  put: <T>(path: string, opts?: RequestOptions) => request<T>("PUT", path, opts),
  delete: <T>(path: string, opts?: RequestOptions) => request<T>("DELETE", path, opts),
};
