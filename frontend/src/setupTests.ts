import "@testing-library/jest-dom";

import { afterAll, afterEach, beforeAll, vi } from "vitest";

import { server } from "./test/server";

// jsdom lacks matchMedia (used by AntD responsive helpers) and ResizeObserver (used by AntD and
// Recharts). Stub both so components render in tests without throwing.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }) as unknown as MediaQueryList;
}

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// MSW mocks the HTTP boundary (the SPA analog of respx). Unhandled requests fail loudly so a missing
// mock is caught in the test, not silently swallowed.
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  localStorage.clear(); // no session bleed between tests
});
afterAll(() => server.close());
