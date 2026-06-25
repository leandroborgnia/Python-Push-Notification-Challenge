// Auth client — maps to the backend /api/v1/auth surface (contracts/api-client.md). These calls run
// unauthenticated (auth: false) except `me`, which is the token-validity probe.

import { httpClient } from "./http";
import type { MeResponse, TokenResponse } from "./types";

export interface StatusResponse {
  status: string;
}

export const auth = {
  register: (email: string, password: string) =>
    httpClient.post<StatusResponse>("/api/v1/auth/register", {
      json: { email, password },
      auth: false,
    }),

  verify: (token: string) =>
    httpClient.post<StatusResponse>("/api/v1/auth/verify", { query: { token }, auth: false }),

  // OAuth2 password grant: the body is urlencoded `username`/`password`, not JSON.
  login: (email: string, password: string) =>
    httpClient.post<TokenResponse>("/api/v1/auth/login", {
      form: { username: email, password },
      auth: false,
    }),

  me: () => httpClient.get<MeResponse>("/api/v1/auth/me"),

  requestReset: (email: string) =>
    httpClient.post<void>("/api/v1/auth/reset-request", { json: { email }, auth: false }),

  confirmReset: (token: string, newPassword: string) =>
    httpClient.post<StatusResponse>("/api/v1/auth/reset-confirm", {
      json: { token, new_password: newPassword },
      auth: false,
    }),
};
