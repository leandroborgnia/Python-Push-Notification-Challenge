import { Spin } from "antd";

/** Shared loading state (FR-035). Polite live region so assistive tech announces the wait. */
export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div style={{ padding: 48, textAlign: "center" }} role="status" aria-live="polite">
      <Spin />
      <div style={{ marginTop: 12 }}>{label}</div>
    </div>
  );
}
