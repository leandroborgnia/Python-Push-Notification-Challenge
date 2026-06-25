// Wire types mirroring the backend `/api/v1` schemas (backend/app/api/schemas.py). The backend is the
// source of truth; the SPA never invents fields. See specs/005-web-frontend-console/data-model.md.

export type Channel = "email" | "sms" | "push";
export type DeliveryState = "queued" | "sent" | "delivered" | "failed";

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
}

export interface MeResponse {
  user_id: string;
}

export interface Contact {
  id: string; // uuid
  display_name: string;
  email: string | null;
  phone: string | null;
  device_token: string | null;
}

export interface ContactCreate {
  display_name: string;
  email?: string | null;
  phone?: string | null;
  device_token?: string | null;
}

export interface Template {
  id: string; // uuid
  title: string;
  content: string;
  channel: Channel;
  recipient_contact_ids: string[];
}

// The create body and the PUT body are identical (everything but the id).
export type TemplateCreate = Omit<Template, "id">;

export interface DispatchAck {
  dispatch_id: string;
  status: "accepted";
}

export interface Transition {
  from_status: DeliveryState | null;
  to_status: DeliveryState;
  reason: string | null;
  attempt: number | null;
  at: string | null; // ISO-8601 UTC; null only in degenerate cases
}

export interface Delivery {
  delivery_id: string;
  recipient_name: string;
  destination: string | null;
  status: DeliveryState;
  failure_reason: string | null;
  transitions: Transition[];
}

export interface Dispatch {
  dispatch_id: string;
  channel: Channel;
  created_at: string | null; // ISO-8601 UTC
  deliveries: Delivery[];
}
