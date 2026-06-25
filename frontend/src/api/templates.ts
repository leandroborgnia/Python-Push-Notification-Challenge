// Templates client (contracts/api-client.md). `send` is consumed by the Send & History page and is
// never called from edit/delete — editing or deleting a template must not dispatch anything (FR-023).

import { httpClient } from "./http";
import type { DispatchAck, Template, TemplateCreate } from "./types";

export const templates = {
  list: (limit = 100, offset = 0) =>
    httpClient.get<Template[]>("/api/v1/templates", { query: { limit, offset } }),

  create: (body: TemplateCreate) => httpClient.post<Template>("/api/v1/templates", { json: body }),

  update: (id: string, body: TemplateCreate) =>
    httpClient.put<Template>(`/api/v1/templates/${id}`, { json: body }),

  remove: (id: string) => httpClient.delete<void>(`/api/v1/templates/${id}`),

  send: (id: string) => httpClient.post<DispatchAck>(`/api/v1/templates/${id}/send`),
};
