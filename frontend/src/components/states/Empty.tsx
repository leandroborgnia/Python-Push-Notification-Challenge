import { Empty as AntEmpty } from "antd";
import type { ReactNode } from "react";

/** Shared empty state (FR-035): a friendly "nothing here yet" with optional call-to-action. */
export function Empty({ description, action }: { description: string; action?: ReactNode }) {
  return (
    <div style={{ padding: 48 }}>
      <AntEmpty description={description}>{action}</AntEmpty>
    </div>
  );
}
