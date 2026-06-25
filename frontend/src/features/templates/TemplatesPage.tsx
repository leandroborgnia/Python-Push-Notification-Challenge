// Manage templates (US3, FR-018..023): a paginated table with single-row selection enabling
// Edit/Delete, a create/edit modal (title, content, one channel, recipients from contacts), SMS≤160
// enforced client-side with server 422s surfaced, delete-with-confirmation, and — crucially —
// editing or deleting NEVER sends. Mutations invalidate ['templates'] so the table self-refreshes.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, Button, Card, Form, Input, Modal, Select, Space, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useState } from "react";

import { templates } from "../../api/templates";
import type { Channel, Template, TemplateCreate } from "../../api/types";
import { Empty, ErrorState, Loading } from "../../components/states";
import { isApiError } from "../../lib/errors";
import { SMS_MAX_LENGTH } from "../../lib/validation";
import { RecipientSelect } from "./RecipientSelect";

const PAGE_SIZE = 10;

const CHANNEL_OPTIONS: { label: string; value: Channel }[] = [
  { label: "Email", value: "email" },
  { label: "SMS", value: "sms" },
  { label: "Push", value: "push" },
];

const CHANNEL_COLORS: Record<Channel, string> = { email: "blue", sms: "green", push: "purple" };

interface TemplateForm {
  title: string;
  content: string;
  channel: Channel;
  recipient_contact_ids: string[];
}

export function TemplatesPage() {
  const { message } = AntApp.useApp();
  const { modal } = AntApp.useApp();
  const queryClient = useQueryClient();
  // Untyped form instance so setFields can carry arbitrary server field names.
  const [form] = Form.useForm();
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Template | "new" | null>(null);

  const offset = (page - 1) * PAGE_SIZE;
  const query = useQuery({
    queryKey: ["templates", page],
    queryFn: () => templates.list(PAGE_SIZE, offset),
  });

  const rows = query.data ?? [];
  const selected = rows.find((t) => t.id === selectedId) ?? null;

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["templates"] });
  }

  function surface(err: unknown) {
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
  }

  const save = useMutation({
    mutationFn: (body: TemplateCreate) =>
      editing && editing !== "new" ? templates.update(editing.id, body) : templates.create(body),
    onSuccess: () => {
      message.success(editing && editing !== "new" ? "Template updated." : "Template created.");
      setEditing(null);
      form.resetFields();
      refresh();
    },
    onError: surface,
  });

  const remove = useMutation({
    mutationFn: (id: string) => templates.remove(id),
    onSuccess: () => {
      message.success("Template deleted.");
      setSelectedId(null);
      refresh();
    },
    onError: surface,
  });

  function openCreate() {
    setEditing("new");
    form.resetFields();
    form.setFieldsValue({ channel: "email", recipient_contact_ids: [] });
  }

  function openEdit() {
    if (!selected) return;
    setEditing(selected);
    form.setFieldsValue({
      title: selected.title,
      content: selected.content,
      channel: selected.channel,
      recipient_contact_ids: selected.recipient_contact_ids,
    });
  }

  function confirmDelete() {
    if (!selected) return;
    modal.confirm({
      title: "Delete this template?",
      content: `“${selected.title}” will be permanently removed. This does not send anything.`,
      okText: "Delete",
      okButtonProps: { danger: true },
      onOk: () => remove.mutateAsync(selected.id),
    });
  }

  function onSubmit(values: TemplateForm) {
    save.mutate({
      title: values.title,
      content: values.content,
      channel: values.channel,
      recipient_contact_ids: values.recipient_contact_ids,
    });
  }

  const columns: ColumnsType<Template> = [
    { title: "Title", dataIndex: "title", key: "title" },
    {
      title: "Channel",
      dataIndex: "channel",
      key: "channel",
      render: (c: Channel) => <Tag color={CHANNEL_COLORS[c]}>{c.toUpperCase()}</Tag>,
    },
    {
      title: "Content",
      dataIndex: "content",
      key: "content",
      ellipsis: true,
    },
    {
      title: "Recipients",
      dataIndex: "recipient_contact_ids",
      key: "recipients",
      render: (ids: string[]) => ids.length,
    },
  ];

  const fullPage = rows.length === PAGE_SIZE;
  const inferredTotal = offset + rows.length + (fullPage ? 1 : 0);

  return (
    <Card
      title="Templates"
      extra={
        <Space>
          <Button onClick={openEdit} disabled={!selected}>
            Edit
          </Button>
          <Button danger onClick={confirmDelete} disabled={!selected}>
            Delete
          </Button>
          <Button type="primary" onClick={openCreate}>
            New template
          </Button>
        </Space>
      }
    >
      {query.isLoading ? (
        <Loading label="Loading templates…" />
      ) : query.isError ? (
        <ErrorState
          message={isApiError(query.error) ? query.error.detail : undefined}
          onRetry={() => void query.refetch()}
        />
      ) : rows.length === 0 && page === 1 ? (
        <Empty
          description="No templates yet"
          action={
            <Button type="primary" onClick={openCreate}>
              Create one
            </Button>
          }
        />
      ) : (
        <Table
          rowKey="id"
          columns={columns}
          dataSource={rows}
          scroll={{ x: "max-content" }}
          rowSelection={{
            type: "radio",
            selectedRowKeys: selectedId ? [selectedId] : [],
            onChange: (keys) => setSelectedId((keys[0] as string) ?? null),
          }}
          pagination={{
            current: page,
            pageSize: PAGE_SIZE,
            total: inferredTotal,
            showSizeChanger: false,
            onChange: setPage,
          }}
        />
      )}

      <Modal
        open={editing !== null}
        title={editing && editing !== "new" ? "Edit template" : "New template"}
        okText="Save"
        confirmLoading={save.isPending}
        onOk={() => form.submit()}
        onCancel={() => {
          setEditing(null);
          form.resetFields();
        }}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={onSubmit} requiredMark={false}>
          <Form.Item
            label="Title"
            name="title"
            rules={[{ required: true, message: "A title is required" }]}
          >
            <Input placeholder="Welcome message" />
          </Form.Item>
          <Form.Item label="Channel" name="channel" rules={[{ required: true }]}>
            <Select
              options={CHANNEL_OPTIONS}
              onChange={() => {
                // Re-check the SMS length rule against the newly selected channel.
                void form.validateFields(["content"]).catch(() => undefined);
              }}
            />
          </Form.Item>
          <Form.Item
            label="Content"
            name="content"
            rules={[
              { required: true, message: "Content is required" },
              {
                validator: (_r, v: string) =>
                  form.getFieldValue("channel") === "sms" && (v?.length ?? 0) > SMS_MAX_LENGTH
                    ? Promise.reject(
                        new Error(`SMS messages are limited to ${SMS_MAX_LENGTH} characters`),
                      )
                    : Promise.resolve(),
              },
            ]}
          >
            <Input.TextArea autoSize={{ minRows: 3, maxRows: 8 }} />
          </Form.Item>
          <Form.Item
            label="Recipients"
            name="recipient_contact_ids"
            rules={[
              {
                validator: (_r, v: string[]) =>
                  v && v.length > 0
                    ? Promise.resolve()
                    : Promise.reject(new Error("Select at least one recipient")),
              },
            ]}
          >
            <RecipientSelect />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
