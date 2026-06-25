// Signed-in shell: AntD Layout with a top app bar (product name • signed-in email • logout) and tab
// navigation whose active tab is derived from the URL (FR-002/003). Renders the active page via
// <Outlet/>.

import { Button, Grid, Layout, Menu, Space, Typography } from "antd";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthProvider";

const { Header, Content } = Layout;
const { useBreakpoint } = Grid;

const TABS = [
  { key: "/", label: "Home" },
  { key: "/contacts", label: "Contacts" },
  { key: "/templates", label: "Templates" },
  { key: "/sends", label: "Send & History" },
];

export function AppShell() {
  const { session, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const screens = useBreakpoint();

  // Active tab from the URL: exact "/" for Home, otherwise the first path segment.
  const activeKey = location.pathname === "/" ? "/" : `/${location.pathname.split("/")[1]}`;

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header
        style={{
          display: "flex",
          alignItems: "center",
          gap: 24,
          paddingInline: 16,
        }}
      >
        <Typography.Text strong style={{ color: "#fff", fontSize: 16, whiteSpace: "nowrap" }}>
          Notification Admin
        </Typography.Text>
        <Menu
          theme="dark"
          mode="horizontal"
          selectedKeys={[activeKey]}
          items={TABS}
          onClick={({ key }) => navigate(key)}
          style={{ flex: 1, minWidth: 0 }}
        />
        <Space>
          {screens.md && session ? (
            <Typography.Text style={{ color: "rgba(255,255,255,0.85)" }}>
              {session.email}
            </Typography.Text>
          ) : null}
          <Button onClick={logout}>Log out</Button>
        </Space>
      </Header>
      <Content style={{ padding: 24 }}>
        <Outlet />
      </Content>
    </Layout>
  );
}
