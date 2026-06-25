import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import { App as AntApp, ConfigProvider } from "antd";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";

import { AuthProvider } from "../auth/AuthProvider";

// Wrap a unit-under-test in the same provider tree the app uses (TanStack Query, AntD App context for
// toasts/modals, Router, AuthProvider). Retries are off so error assertions resolve immediately.
export function renderWithProviders(
  ui: ReactElement,
  options: { initialEntries?: string[] } = {},
): RenderResult {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ConfigProvider>
        <AntApp>
          <MemoryRouter initialEntries={options.initialEntries ?? ["/"]}>
            <AuthProvider>{ui}</AuthProvider>
          </MemoryRouter>
        </AntApp>
      </ConfigProvider>
    </QueryClientProvider>,
  );
}
