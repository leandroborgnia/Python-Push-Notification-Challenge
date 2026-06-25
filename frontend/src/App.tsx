// Composition root for the SPA: the provider tree (TanStack Query, AntD ConfigProvider + App,
// Router, AuthProvider) and the route table (public auth surfaces + the RequireAuth-guarded shell).

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntApp, ConfigProvider } from "antd";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider } from "./auth/AuthProvider";
import { RequireAuth } from "./auth/RequireAuth";
import { AppShell } from "./components/AppShell";
import { AuthPage } from "./features/auth/AuthPage";
import { ContactsPage } from "./features/contacts/ContactsPage";
import { Dashboard } from "./features/home/Dashboard";
import { SendHistoryPage } from "./features/sends/SendHistoryPage";
import { TemplatesPage } from "./features/templates/TemplatesPage";
import { isApiError } from "./lib/errors";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Never retry 4xx (validation/auth/not-found); allow one retry for transient/5xx failures.
      retry: (failureCount, error) => {
        if (isApiError(error) && error.status >= 400 && error.status < 500) return false;
        return failureCount < 1;
      },
      refetchOnWindowFocus: false,
    },
    mutations: { retry: false },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider>
        <AntApp>
          <BrowserRouter>
            <AuthProvider>
              <Routes>
                {/* Public auth surfaces — a single page in five modes plus deep-link landings. */}
                <Route path="/auth" element={<AuthPage />} />
                <Route path="/verify" element={<AuthPage />} />
                <Route path="/reset" element={<AuthPage />} />

                {/* Signed-in shell. */}
                <Route element={<RequireAuth />}>
                  <Route path="/" element={<AppShell />}>
                    <Route index element={<Dashboard />} />
                    <Route path="contacts" element={<ContactsPage />} />
                    <Route path="templates" element={<TemplatesPage />} />
                    <Route path="sends" element={<SendHistoryPage />} />
                  </Route>
                </Route>

                {/* Unknown path → "/", which RequireAuth resolves to the shell or /auth. */}
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </AuthProvider>
          </BrowserRouter>
        </AntApp>
      </ConfigProvider>
    </QueryClientProvider>
  );
}
