import { defineConfig, devices } from "@playwright/test";

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
  // 共享 demo 后端 + 共享 DB：串行执行避免写操作（建组/批量移动/已读）互相踩踏
  workers: 1,
  fullyParallel: false,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    locale: "zh-CN",
  },
  webServer: {
    // 每次测试运行都从空库重新播种，保证 demo 数据（24 UP / 2 待审 / 2 提醒）可复现。
    // 注意 DATA_DIR 由后端在 cd 之后按仓库根解析（../../.e2e-data），清理须在同一路径上。
    command: `cd ../../ && rm -rf ../../.e2e-data && uv run uvicorn app.main:app --host 127.0.0.1 --port ${PORT}`,
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
  // 桌面 1440x900（Chromium + WebKit 覆盖双引擎）+ 移动 390x844 触摸
  projects: [
    { name: "chromium-desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "webkit-desktop", use: { ...devices["Desktop Safari"], viewport: { width: 1440, height: 900 } } },
    { name: "chromium-mobile", use: { ...devices["iPhone 13"], viewport: { width: 390, height: 844 } } },
  ],
});
