// One auth surface for the whole account lifecycle (FR-006..FR-013): Login (default), Register,
// Verify, Request reset, and Confirm reset — switchable in place. The /verify and /reset routes are
// deep-link landings that read ?token=; /verify auto-submits, /reset prefills the token.

import { App as AntApp, Alert, Button, Card, Form, Input, Layout, Space, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { auth } from "../../api/auth";
import { useAuth } from "../../auth/AuthProvider";
import { isApiError } from "../../lib/errors";
import { isValidEmail, isValidPassword, MIN_PASSWORD_LENGTH } from "../../lib/validation";

type Mode = "login" | "register" | "verify" | "request-reset" | "confirm-reset";

const TITLES: Record<Mode, string> = {
  login: "Sign in",
  register: "Create an account",
  verify: "Verify your email",
  "request-reset": "Reset your password",
  "confirm-reset": "Set a new password",
};

function modeForPath(pathname: string): Mode {
  if (pathname === "/verify") return "verify";
  if (pathname === "/reset") return "confirm-reset";
  return "login";
}

const emailRules = [
  { required: true, message: "Email is required" },
  {
    validator: (_r: unknown, v: string) =>
      !v || isValidEmail(v) ? Promise.resolve() : Promise.reject(new Error("Enter a valid email")),
  },
];

const passwordRules = [
  { required: true, message: "Password is required" },
  {
    validator: (_r: unknown, v: string) =>
      !v || isValidPassword(v)
        ? Promise.resolve()
        : Promise.reject(new Error(`At least ${MIN_PASSWORD_LENGTH} characters`)),
  },
];

export function AuthPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { message } = AntApp.useApp();
  const { login } = useAuth();
  const [form] = Form.useForm();

  const initialMode = modeForPath(location.pathname);
  const tokenFromUrl = searchParams.get("token") ?? "";
  const [mode, setMode] = useState<Mode>(initialMode);
  const [submitting, setSubmitting] = useState(false);
  const [pendingEmail, setPendingEmail] = useState<string>("");
  const [autoVerified, setAutoVerified] = useState(false);

  const expired = Boolean((location.state as { expired?: boolean } | null)?.expired);

  // Reset fields when switching modes; prefill the token on the reset deep link.
  useEffect(() => {
    form.resetFields();
    if (mode === "confirm-reset" && tokenFromUrl) {
      form.setFieldsValue({ token: tokenFromUrl });
    }
  }, [mode, tokenFromUrl, form]);

  const applyServerError = useCallback(
    (err: unknown): number | null => {
      if (isApiError(err)) {
        if (err.fieldErrors) {
          form.setFields(
            Object.entries(err.fieldErrors).map(([name, msg]) => ({ name, errors: [msg] })),
          );
        }
        message.error(err.detail);
        return err.status;
      }
      message.error("Something went wrong. Please try again.");
      return null;
    },
    [form, message],
  );

  const runVerify = useCallback(
    async (token: string) => {
      setSubmitting(true);
      try {
        await auth.verify(token);
        message.success("Email verified. You can sign in now.");
        setMode("login");
      } catch (err) {
        applyServerError(err); // 400 invalid/expired/used → server detail surfaced
      } finally {
        setSubmitting(false);
      }
    },
    [applyServerError, message],
  );

  // Deep-link auto-verify: /verify?token=… submits once on load and reports the outcome.
  useEffect(() => {
    if (initialMode === "verify" && tokenFromUrl && !autoVerified) {
      setAutoVerified(true);
      void runVerify(tokenFromUrl);
    }
  }, [initialMode, tokenFromUrl, autoVerified, runVerify]);

  async function onLogin(values: { email: string; password: string }) {
    setSubmitting(true);
    try {
      const res = await auth.login(values.email, values.password);
      login(res.access_token, values.email);
      message.success("Signed in.");
      navigate("/", { replace: true });
    } catch (err) {
      const status = applyServerError(err);
      // Unverified accounts come back as 400 with a "verify" message → reveal the Verify path.
      if (status === 400 && isApiError(err) && /verif/i.test(err.detail)) {
        setPendingEmail(values.email);
        setMode("verify");
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function onRegister(values: { email: string; password: string }) {
    setSubmitting(true);
    try {
      await auth.register(values.email, values.password);
      setPendingEmail(values.email);
      message.success("Account created. Check your email for a verification link.");
      setMode("verify");
    } catch (err) {
      applyServerError(err);
    } finally {
      setSubmitting(false);
    }
  }

  async function onRequestReset(values: { email: string }) {
    setSubmitting(true);
    try {
      await auth.requestReset(values.email);
    } catch {
      // Always acknowledged (no account enumeration) — swallow any failure.
    } finally {
      setSubmitting(false);
      message.success("If that email is registered, a reset link is on its way.");
      setMode("login");
    }
  }

  async function onConfirmReset(values: { token: string; new_password: string }) {
    setSubmitting(true);
    try {
      await auth.confirmReset(values.token.trim(), values.new_password);
      message.success("Password updated. Please sign in.");
      setMode("login");
    } catch (err) {
      applyServerError(err);
    } finally {
      setSubmitting(false);
    }
  }

  function onFinish(values: Record<string, string>) {
    switch (mode) {
      case "login":
        return onLogin({ email: values.email, password: values.password });
      case "register":
        return onRegister({ email: values.email, password: values.password });
      case "verify":
        return runVerify((values.token ?? "").trim());
      case "request-reset":
        return onRequestReset({ email: values.email });
      case "confirm-reset":
        return onConfirmReset({ token: values.token, new_password: values.new_password });
    }
  }

  return (
    <Layout style={{ minHeight: "100vh", placeItems: "center", display: "grid", padding: 16 }}>
      <Card style={{ width: "100%", maxWidth: 420 }} title={TITLES[mode]}>
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          {expired ? (
            <Alert type="warning" showIcon message="Your session expired. Please sign in again." />
          ) : null}

          {mode === "verify" && pendingEmail ? (
            <Alert
              type="info"
              showIcon
              message={`We sent a verification link to ${pendingEmail}. Paste the token below or open the emailed link.`}
            />
          ) : null}

          <Form form={form} layout="vertical" onFinish={onFinish} requiredMark={false}>
            {(mode === "login" || mode === "register" || mode === "request-reset") && (
              <Form.Item label="Email" name="email" rules={emailRules}>
                <Input autoComplete="email" placeholder="you@example.com" />
              </Form.Item>
            )}

            {(mode === "login" || mode === "register") && (
              <Form.Item label="Password" name="password" rules={passwordRules}>
                <Input.Password
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                />
              </Form.Item>
            )}

            {(mode === "verify" || mode === "confirm-reset") && (
              <Form.Item
                label="Token"
                name="token"
                rules={[{ required: true, message: "Paste the token from your email" }]}
              >
                <Input.TextArea
                  autoSize={{ minRows: 2, maxRows: 4 }}
                  placeholder="Verification token"
                />
              </Form.Item>
            )}

            {mode === "confirm-reset" && (
              <Form.Item label="New password" name="new_password" rules={passwordRules}>
                <Input.Password autoComplete="new-password" />
              </Form.Item>
            )}

            <Button type="primary" htmlType="submit" block loading={submitting}>
              {mode === "login"
                ? "Sign in"
                : mode === "register"
                  ? "Create account"
                  : mode === "verify"
                    ? "Verify"
                    : mode === "request-reset"
                      ? "Send reset link"
                      : "Update password"}
            </Button>
          </Form>

          <ModeLinks mode={mode} onSwitch={setMode} />
        </Space>
      </Card>
    </Layout>
  );
}

function ModeLinks({ mode, onSwitch }: { mode: Mode; onSwitch: (m: Mode) => void }) {
  const link = (label: string, target: Mode) => (
    <Button type="link" size="small" style={{ padding: 0 }} onClick={() => onSwitch(target)}>
      {label}
    </Button>
  );

  if (mode === "login") {
    return (
      <Space direction="vertical" size={4} style={{ width: "100%" }}>
        <Typography.Text>Need an account? {link("Register", "register")}</Typography.Text>
        <Typography.Text>Forgot your password? {link("Reset it", "request-reset")}</Typography.Text>
        <Typography.Text>Have a verification token? {link("Verify", "verify")}</Typography.Text>
      </Space>
    );
  }
  return <Typography.Text>{link("← Back to sign in", "login")}</Typography.Text>;
}
