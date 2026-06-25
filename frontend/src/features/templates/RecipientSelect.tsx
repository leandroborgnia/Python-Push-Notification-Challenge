// Multi-select recipient picker (FR-019). Options are drawn ONLY from the signed-in user's contacts
// (paged through `contacts.list`), searchable for large lists. Controlled so it slots into a Form.Item.

import { useQuery } from "@tanstack/react-query";
import { Select } from "antd";

import { contacts } from "../../api/contacts";
import type { Contact } from "../../api/types";

const PAGE_LIMIT = 100;
const MAX_PAGES = 10; // up to 1,000 contacts — well beyond the modest per-user expectation

async function fetchAllContacts(): Promise<Contact[]> {
  const all: Contact[] = [];
  let offset = 0;
  for (let i = 0; i < MAX_PAGES; i += 1) {
    const page = await contacts.list(PAGE_LIMIT, offset);
    all.push(...page);
    if (page.length < PAGE_LIMIT) break;
    offset += PAGE_LIMIT;
  }
  return all;
}

export function RecipientSelect({
  value,
  onChange,
}: {
  value?: string[];
  onChange?: (value: string[]) => void;
}) {
  const query = useQuery({ queryKey: ["contacts", "all"], queryFn: fetchAllContacts });
  const options = (query.data ?? []).map((c) => ({
    label: c.email ? `${c.display_name} (${c.email})` : c.display_name,
    value: c.id,
  }));

  return (
    <Select
      mode="multiple"
      value={value}
      onChange={onChange}
      options={options}
      loading={query.isLoading}
      placeholder="Select recipients from your contacts"
      optionFilterProp="label"
      showSearch
      notFoundContent={query.isLoading ? "Loading…" : "No contacts — add some first"}
    />
  );
}
