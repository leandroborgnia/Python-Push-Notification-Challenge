// Personal sending dashboard (US5, FR-029..034): pages /sends client-side (limit=100, up to a
// 2,000-dispatch cap = ≤20 calls) under a loading state, aggregates per-UTC-hour with the pure
// `aggregate`, and renders a 24-bar Recharts chart + summary stats. A "recent window" indicator
// appears when the scan hit the cap; manual Refresh re-aggregates (['dashboard']).

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Col, Row, Space, Statistic, Tag, Typography } from "antd";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { sends } from "../../api/sends";
import type { Dispatch } from "../../api/types";
import { Empty, ErrorState, Loading } from "../../components/states";
import { aggregate, type HourAggregate } from "../../lib/aggregate";
import { isApiError } from "../../lib/errors";

const PAGE = 100;
const CAP = 2000; // recent-window bound (research R7), tunable here
const MAX_CALLS = CAP / PAGE; // 20 sequential pages

async function loadDashboard(): Promise<HourAggregate> {
  const dispatches: Dispatch[] = [];
  let offset = 0;
  let capped = false;
  for (let i = 0; i < MAX_CALLS; i += 1) {
    const page = await sends.list(PAGE, offset);
    dispatches.push(...page);
    if (page.length < PAGE) break; // history exhausted
    offset += PAGE;
    if (dispatches.length >= CAP) {
      capped = true;
      break;
    }
  }
  return aggregate(dispatches, capped);
}

function HourChart({ buckets }: { buckets: number[] }) {
  const data = buckets.map((count, hour) => ({
    hour: String(hour).padStart(2, "0"),
    count,
  }));
  return (
    <div style={{ width: "100%", height: 320 }} role="img" aria-label="Sends per UTC hour">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="hour" interval={0} tick={{ fontSize: 11 }} />
          <YAxis allowDecimals={false} />
          <Tooltip />
          <Bar dataKey="count" fill="#1677ff" name="Sent" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function Dashboard() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["dashboard"], queryFn: loadDashboard });

  if (query.isLoading) return <Loading label="Aggregating your sends…" />;
  if (query.isError) {
    return (
      <ErrorState
        message={isApiError(query.error) ? query.error.detail : undefined}
        onRetry={() => void query.refetch()}
      />
    );
  }

  const agg = query.data!;
  const mostRecent = agg.mostRecentSentAt ? new Date(agg.mostRecentSentAt).toLocaleString() : "—";

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Row align="middle" justify="space-between">
        <Col>
          <Typography.Title level={3} style={{ margin: 0 }}>
            Your sending activity
          </Typography.Title>
          {agg.capped ? (
            <Tag color="orange" style={{ marginTop: 8 }}>
              Recent window — showing the latest {CAP.toLocaleString()} sends
            </Tag>
          ) : null}
        </Col>
        <Col>
          <Button onClick={() => void queryClient.invalidateQueries({ queryKey: ["dashboard"] })}>
            Refresh
          </Button>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic title="Messages sent" value={agg.totalSent} />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic title="Sends scanned" value={agg.dispatchesScanned} />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic title="Most recent send" value={mostRecent} valueStyle={{ fontSize: 16 }} />
          </Card>
        </Col>
      </Row>

      <Card title="Sends per hour (UTC)">
        {agg.totalSent === 0 ? (
          <Empty description="No sends yet — your hourly chart will fill in as you send." />
        ) : (
          <HourChart buckets={agg.buckets} />
        )}
      </Card>
    </Space>
  );
}
