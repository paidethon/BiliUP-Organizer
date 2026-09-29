import { defineConfig } from "@playwright/test";

/**
 * E2E suite runs against the backend in demo mode (synthetic data, no external
 * network calls). The backend serves the built SPA from apps/web/dist, so run
 * `npm run build` in apps/web before `npx playwright test`.
 */
const PORT = 8067;

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    locale: "zh-CN",
  },
  webServer: {
    command: `cd ../../ && uv run uvicorn app.main:app --host 127.0.0.1 --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/healthz`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    env: {
      DEMO_MODE: "1",
      APP_ENV: "test",
      ENABLE_SCHEDULER: "0",
      DATA_DIR: "../../.e2e-data",
    },
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
