// Contacts client (contracts/api-client.md). The backend caps `limit` at 100.

import { httpClient } from "./http";
import type { Contact, ContactCreate } from "./types";

export const contacts = {
  list: (limit = 100, offset = 0) =>
    httpClient.get<Contact[]>("/api/v1/contacts", { query: { limit, offset } }),

  create: (body: ContactCreate) => httpClient.post<Contact>("/api/v1/contacts", { json: body }),
};
