// Sends client (contracts/api-client.md). `list` returns full per-delivery transitions, so the
// dashboard can aggregate straight from the list pages with no per-dispatch fan-out.

import { httpClient } from "./http";
import type { Dispatch } from "./types";

export const sends = {
  list: (limit = 100, offset = 0) =>
    httpClient.get<Dispatch[]>("/api/v1/sends", { query: { limit, offset } }),

  get: (id: string) => httpClient.get<Dispatch>(`/api/v1/sends/${id}`),
};
