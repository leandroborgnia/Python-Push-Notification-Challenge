/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/setupTests.ts"],
    // Give the transport an absolute API base in tests so node's fetch (and MSW) can parse the URL;
    // MSW handlers match any origin via a leading wildcard.
    env: { VITE_API_BASE_URL: "http://api.localhost" },
  },
});
