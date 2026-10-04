import { expect, test, type Page } from "@playwright/test";

/** Classification-job panel lifecycle, fully mocked at the network layer so
 * the shared demo database (which review.spec asserts on) is never touched. */

type JobStatus = "running" | "completed" | "failed" | "paused";

function jobFixture(status: JobStatus, overrides: Record<string, unknown> = {}) {
  return {
    id: 901,
    kind: "full",
    status,
    batch_size: 20,
    auto_apply: false,
    threshold: 0.9,
    total: 24,
    processed: status === "running" ? 4 : 24,
    classified: status === "running" ? 3 : 20,
    auto_applied: 0,
    needs_review: status === "running" ? 3 : 16,
    unclassifiable: status === "running" ? 0 : 3,
    failed: status === "failed" ? 5 : 0,
    error: null,
    created_at: "2026-10-01 12:00:00",
    finished_at: status === "running" ? null : "2026-10-01 12:05:00",
    ...overrides,
  };
}

async function mockJobs(page: Page, state: { current: JobStatus; runningPollsLeft: number }) {
  await page.route("**/api/v1/review/jobs**", (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    const path = url.pathname;
    if (path.endsWith("/current")) {
      if (state.current === "none") return route.fulfill({ json: null });
      if (state.runningPollsLeft > 0) {
        state.runningPollsLeft -= 1;
        return route.fulfill({ json: jobFixture("running") });
      }
      return route.fulfill({ json: jobFixture(state.current) });
    }
    if (method === "POST" && path.endsWith("/api/v1/review/jobs")) {
      state.current = "completed"; // the "job" finishes right after creation
      state.runningPollsLeft = 2; // first two polls show a running job
      return route.fulfill({ json: jobFixture("running", { processed: 0, classified: 0, needs_review: 0 }) });
    }
    if (method === "POST" && path.endsWith("/retry-failures")) {
      state.current = "completed";
      return route.fulfill({ json: jobFixture("completed") });
    }
    if (method === "POST" && path.endsWith("/pause")) {
      state.current = "paused";
      return route.fulfill({ json: jobFixture("paused") });
    }
    if (method === "POST" && path.endsWith("/resume")) {
      state.current = "running";
      return route.fulfill({ json: jobFixture("running") });
    }
    if (method === "POST" && path.endsWith("/cancel")) {
      state.current = "completed";
      return route.fulfill({ json: jobFixture("completed") });
    }
    return route.fulfill({ json: { items: state.current === "none" ? [] : [jobFixture(state.current)] } });
  });
}

async function login(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("用户名").fill("e2e");
  await page.getByLabel("密码").fill("e2e-demo");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page).toHaveURL("/");
}

test("创建全量分类任务并显示进度与完成状态", async ({ page }) => {
  const state = { current: "none" as JobStatus, runningPollsLeft: 0 };
  await mockJobs(page, state);
  await login(page);
  await page.goto("/review");
  page.on("dialog", (dialog) => void dialog.accept());

  const fullButton = page.getByRole("button", { name: "重新分类全部" });
  await expect(fullButton).toBeVisible();
  await fullButton.click();

  // panel switches to the running job with counters, then reaches a terminal state
  await expect(page.getByText(/总数|进度/).first()).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("已完成").first()).toBeVisible({ timeout: 20_000 });
});

test("页面刷新后任务状态仍在", async ({ page }) => {
  const state = { current: "completed" as JobStatus, runningPollsLeft: 0 };
  await mockJobs(page, state);
  await login(page);
  await page.goto("/review");
  await expect(page.getByText(/总数|进度/).first()).toBeVisible({ timeout: 10_000 });
  await page.reload();
  await expect(page.getByText(/总数|进度/).first()).toBeVisible({ timeout: 10_000 });
});

test("失败项可重试", async ({ page }) => {
  const state = { current: "failed" as JobStatus, runningPollsLeft: 0 };
  await mockJobs(page, state);
  await login(page);
  await page.goto("/review");

  const retry = page.getByRole("button", { name: /重试失败/ });
  await expect(retry).toBeVisible({ timeout: 10_000 });
  await retry.click();
  await expect(page.getByText("已完成").first()).toBeVisible({ timeout: 20_000 });
});
