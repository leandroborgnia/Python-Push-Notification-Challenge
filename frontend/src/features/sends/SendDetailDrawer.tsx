// Per-send detail (FR-026/027): a drawer listing each recipient's current state, destination, and
// failure reason, plus the full append-only transition timeline. While open and non-terminal it
// polls ['send', id] every 4s so statuses advance without a page reload.

import { useQuery } from "@tanstack/react-query";
import { Card, Drawer, Empty, Space, Tag, Timeline, Typography } from "antd";

import { sends } from "../../api/sends";
import type { Delivery, Transition } from "../../api/types";
import { isApiError } from "../../lib/errors";
import { Loading } from "../../components/states";
import { dispatchInProgress, STATE_COLOR } from "./status";

function formatAt(at: string | null): string {
  if (!at) return "—";
  const ms = Date.parse(at);
  return Number.isNaN(ms) ? at : new Date(ms).toLocaleString();
}

function transitionItems(transitions: Transition[]) {
  return transitions.map((t, idx) => ({
    key: idx,
    color: STATE_COLOR[t.to_status],
    children: (
      <span>
        <strong>
          {t.from_status ?? "∅"} → {t.to_status}
        </strong>{" "}
        <Typography.Text type="secondary">
          {formatAt(t.at)}
          {t.attempt != null ? ` · attempt ${t.attempt}` : ""}
          {t.reason ? ` · ${t.reason}` : ""}
        </Typography.Text>
      </span>
    ),
  }));
}

function DeliveryCard({ delivery }: { delivery: Delivery }) {
  return (
    <Card size="small" title={delivery.recipient_name}>
      <Space direction="vertical" size="small" style={{ width: "100%" }}>
        <Space wrap>
          <Tag color={STATE_COLOR[delivery.status]}>{delivery.status.toUpperCase()}</Tag>
          <Typography.Text type="secondary">{delivery.destination ?? "—"}</Typography.Text>
        </Space>
        {delivery.failure_reason ? (
          <Typography.Text type="danger">{delivery.failure_reason}</Typography.Text>
        ) : null}
        <Timeline items={transitionItems(delivery.transitions)} />
      </Space>
    </Card>
  );
}

export function SendDetailDrawer({
  dispatchId,
  open,
  onClose,
}: {
  dispatchId: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const query = useQuery({
    queryKey: ["send", dispatchId],
    queryFn: () => sends.get(dispatchId as string),
    enabled: open && dispatchId !== null,
    refetchInterval: (q) => (q.state.data && dispatchInProgress(q.state.data) ? 4000 : false),
  });

  const dispatch = query.data;

  return (
    <Drawer title="Send detail" width={520} open={open} onClose={onClose} destroyOnClose>
      {query.isLoading ? (
        <Loading label="Loading send…" />
      ) : query.isError ? (
        <Empty description={isApiError(query.error) ? query.error.detail : "Could not load."} />
      ) : !dispatch || dispatch.deliveries.length === 0 ? (
        <Empty description="No recipients on this send." />
      ) : (
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          {dispatch.deliveries.map((d) => (
            <DeliveryCard key={d.delivery_id} delivery={d} />
          ))}
        </Space>
      )}
    </Drawer>
  );
}
