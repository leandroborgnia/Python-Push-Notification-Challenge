// Send a template and track delivery (US4, FR-024..028): a non-blocking send form (pick one template
// → "Accepted for delivery" toast ≤2s), a paginated history table with per-send status that polls
// every 4s while anything is non-terminal (manual Refresh re-fetches), and a per-send detail drawer.
// Only sends the backend returns appear here — server-owned stats-report sends are never listed.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, Button, Card, Select, Space, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useState } from "react";

import { sends } from "../../api/sends";
import { templates } from "../../api/templates";
import type { Channel, Dispatch, Template } from "../../api/types";
import { Empty, ErrorState, Loading } from "../../components/states";
import { isApiError } from "../../lib/errors";
import { SendDetailDrawer } from "./SendDetailDrawer";
import { anyInProgress, dispatchInProgress, STATE_COLOR, STATE_ORDER, stateCounts } from "./status";

const PAGE_SIZE = 10;
const POLL_MS = 4000;

const CHANNEL_COLORS: Record<Channel, string> = { email: "blue", sms: "green", push: "purple" };

async function fetchAllTemplates(): Promise<Template[]> {
  const all: Template[] = [];
  let offset = 0;
  for (let i = 0; i < 10; i += 1) {
    const page = await templates.list(100, offset);
    all.push(...page);
    if (page.length < 100) break;
    offset += 100;
  }
  return all;
}

function StatusCell({ dispatch }: { dispatch: Dispatch }) {
  const counts = stateCounts(dispatch);
  return (
    <Space size={4} wrap>
      {STATE_ORDER.filter((s) => counts[s] > 0).map((s) => (
        <Tag key={s} color={STATE_COLOR[s]}>
          {counts[s]} {s}
        </Tag>
      ))}
      {dispatchInProgress(dispatch) ? <Tag>in progress…</Tag> : null}
    </Space>
  );
}

export function SendHistoryPage() {
  const { message } = AntApp.useApp();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [templateId, setTemplateId] = useState<string | undefined>();
  const [openId, setOpenId] = useState<string | null>(null);

  const offset = (page - 1) * PAGE_SIZE;
  const query = useQuery({
    queryKey: ["sends", page],
    queryFn: () => sends.list(PAGE_SIZE, offset),
    refetchInterval: (q) => (anyInProgress(q.state.data) ? POLL_MS : false),
  });

  const templatesQuery = useQuery({ queryKey: ["templates", "all"], queryFn: fetchAllTemplates });

  const send = useMutation({
    mutationFn: (id: string) => templates.send(id),
    onSuccess: () => {
      // 202 returns immediately; acknowledge without blocking (SC-010).
      message.success("Accepted for delivery.");
      void queryClient.invalidateQueries({ queryKey: ["sends"] });
    },
    onError: (err: unknown) => {
      message.error(
        isApiError(err) ? err.detail : "Could not send. Please check the template and try again.",
      );
    },
  });

  const rows = query.data ?? [];
  const fullPage = rows.length === PAGE_SIZE;
  const inferredTotal = offset + rows.length + (fullPage ? 1 : 0);

  const columns: ColumnsType<Dispatch> = [
    {
      title: "When",
      dataIndex: "created_at",
      key: "created_at",
      render: (v: string | null) => (v ? new Date(v).toLocaleString() : "—"),
    },
    {
      title: "Channel",
      dataIndex: "channel",
      key: "channel",
      render: (c: Channel) => <Tag color={CHANNEL_COLORS[c]}>{c.toUpperCase()}</Tag>,
    },
    {
      title: "Recipients",
      key: "recipients",
      render: (_v, d) => d.deliveries.length,
    },
    {
      title: "Status",
      key: "status",
      render: (_v, d) => <StatusCell dispatch={d} />,
    },
  ];

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Card title="Send a template">
        <Space wrap>
          <Select
            style={{ minWidth: 280 }}
            placeholder="Choose a template to send"
            value={templateId}
            onChange={setTemplateId}
            loading={templatesQuery.isLoading}
            showSearch
            optionFilterProp="label"
            options={(templatesQuery.data ?? []).map((t) => ({
              label: `${t.title} (${t.channel})`,
              value: t.id,
            }))}
            notFoundContent={
              templatesQuery.isLoading ? "Loading…" : "No templates — create one first"
            }
          />
          <Button
            type="primary"
            disabled={!templateId}
            loading={send.isPending}
            onClick={() => templateId && send.mutate(templateId)}
          >
            Send
          </Button>
        </Space>
      </Card>

      <Card
        title="Send history"
        extra={
          <Button onClick={() => void queryClient.invalidateQueries({ queryKey: ["sends"] })}>
            Refresh
          </Button>
        }
      >
        {query.isLoading ? (
          <Loading label="Loading sends…" />
        ) : query.isError ? (
          <ErrorState
            message={isApiError(query.error) ? query.error.detail : undefined}
            onRetry={() => void query.refetch()}
          />
        ) : rows.length === 0 && page === 1 ? (
          <Empty description="No sends yet — send a template above." />
        ) : (
          <Table
            rowKey="dispatch_id"
            columns={columns}
            dataSource={rows}
            scroll={{ x: "max-content" }}
            onRow={(record) => ({
              onClick: () => setOpenId(record.dispatch_id),
              style: { cursor: "pointer" },
            })}
            pagination={{
              current: page,
              pageSize: PAGE_SIZE,
              total: inferredTotal,
              showSizeChanger: false,
              onChange: setPage,
            }}
          />
        )}
      </Card>

      <SendDetailDrawer
        dispatchId={openId}
        open={openId !== null}
        onClose={() => setOpenId(null)}
      />
    </Space>
  );
}
