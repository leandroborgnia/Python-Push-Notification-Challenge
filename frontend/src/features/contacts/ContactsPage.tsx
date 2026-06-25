// Manage contacts (US2, FR-014..017): a create form (display name + any combination of
// email/phone/device token, ≥1 required) and a read-only paginated table. Creating invalidates the
// ['contacts'] query so the table refreshes without a manual reload.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, Button, Card, Col, Form, Input, Row, Space, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useState } from "react";

import { contacts } from "../../api/contacts";
import type { Contact, ContactCreate } from "../../api/types";
import { Empty, ErrorState, Loading } from "../../components/states";
import { isApiError } from "../../lib/errors";
import { hasAtLeastOneDestination, isValidEmail } from "../../lib/validation";

const PAGE_SIZE = 10;

const columns: ColumnsType<Contact> = [
  { title: "Name", dataIndex: "display_name", key: "display_name" },
  { title: "Email", dataIndex: "email", key: "email", render: (v: string | null) => v ?? "—" },
  { title: "Phone", dataIndex: "phone", key: "phone", render: (v: string | null) => v ?? "—" },
  {
    title: "Device token",
    dataIndex: "device_token",
    key: "device_token",
    render: (v: string | null) => v ?? "—",
  },
];

interface ContactForm {
  display_name: string;
  email?: string;
  phone?: string;
  device_token?: string;
}

export function ContactsPage() {
  const { message } = AntApp.useApp();
  const queryClient = useQueryClient();
  // Untyped form instance so setFields can carry arbitrary server field names (email/phone/…).
  const [form] = Form.useForm();
  const [page, setPage] = useState(1);

  const offset = (page - 1) * PAGE_SIZE;
  const query = useQuery({
    queryKey: ["contacts", page],
    queryFn: () => contacts.list(PAGE_SIZE, offset),
  });

  const create = useMutation({
    mutationFn: (body: ContactCreate) => contacts.create(body),
    onSuccess: () => {
      message.success("Contact added.");
      form.resetFields();
      setPage(1);
      void queryClient.invalidateQueries({ queryKey: ["contacts"] });
    },
    onError: (err: unknown) => {
      if (isApiError(err)) {
        if (err.fieldErrors) {
          form.setFields(
            Object.entries(err.fieldErrors).map(([name, msg]) => ({ name, errors: [msg] })),
          );
        }
        message.error(err.detail);
      } else {
        message.error("Something went wrong. Please try again.");
      }
    },
  });

  function onFinish(values: ContactForm) {
    // Client fast-fail; the server enforces the same rule and any 422 is still surfaced.
    if (!hasAtLeastOneDestination(values)) {
      message.error("Add at least one destination: email, phone, or device token.");
      return;
    }
    create.mutate({
      display_name: values.display_name,
      email: values.email?.trim() || null,
      phone: values.phone?.trim() || null,
      device_token: values.device_token?.trim() || null,
    });
  }

  const rows = query.data ?? [];
  const fullPage = rows.length === PAGE_SIZE;
  // The backend returns no total; infer one so the pager can offer "next" while a page is full.
  const inferredTotal = offset + rows.length + (fullPage ? 1 : 0);

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Card title="Add a contact">
        <Form form={form} layout="vertical" onFinish={onFinish} requiredMark={false}>
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item
                label="Display name"
                name="display_name"
                rules={[{ required: true, message: "A display name is required" }]}
              >
                <Input placeholder="Ada Lovelace" />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item
                label="Email"
                name="email"
                rules={[
                  {
                    validator: (_r, v: string) =>
                      !v || isValidEmail(v)
                        ? Promise.resolve()
                        : Promise.reject(new Error("Enter a valid email")),
                  },
                ]}
              >
                <Input placeholder="ada@example.com" />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label="Phone" name="phone">
                <Input placeholder="+1 555 123 4567" />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label="Device token" name="device_token">
                <Input placeholder="Push device token" />
              </Form.Item>
            </Col>
          </Row>
          <Button type="primary" htmlType="submit" loading={create.isPending}>
            Add contact
          </Button>
        </Form>
      </Card>

      <Card title="Contacts">
        {query.isLoading ? (
          <Loading label="Loading contacts…" />
        ) : query.isError ? (
          <ErrorState
            message={isApiError(query.error) ? query.error.detail : undefined}
            onRetry={() => void query.refetch()}
          />
        ) : rows.length === 0 && page === 1 ? (
          <Empty description="No contacts yet — add your first above." />
        ) : (
          <Table
            rowKey="id"
            columns={columns}
            dataSource={rows}
            scroll={{ x: "max-content" }}
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
    </Space>
  );
}
