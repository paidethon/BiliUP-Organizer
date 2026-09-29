import { expect, test, type Page } from "@playwright/test";

/** demo 模式任意凭据可登录；CSRF cookie 由后端下发、前端自动携带。 */
async function login(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("用户名").fill("e2e");
  await page.getByLabel("密码").fill("e2e-demo");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible();
}

const STAT_LABELS = [
  "总 UP 数",
  "未分组",
  "断更 UP",
  "本地分组",
  "待审建议",
  "开放提醒",
  "追踪视频",
  "最近同步",
];

test.describe("仪表盘", () => {
  test("统计卡网格渲染且总 UP 数 ≥ 20", async ({ page }) => {
    await login(page);
    const grid = page.getByRole("region", { name: "统计概览" });
    await expect(grid).toBeVisible();
    for (const label of STAT_LABELS) {
      await expect(grid.getByText(label, { exact: true })).toBeVisible();
    }
    const totalCard = grid.getByRole("link", { name: /总 UP 数/ });
    await expect(totalCard).toBeVisible();
    const aria = await totalCard.getAttribute("aria-label");
    const total = Number(aria?.match(/总 UP 数：(\d+)/)?.[1] ?? 0);
    expect(total).toBeGreaterThanOrEqual(20);
  });

  test("B 站账号卡显示 demo_user 已登录", async ({ page }) => {
    await login(page);
    await expect(page.getByText("demo_user")).toBeVisible();
    await expect(page.getByText("已登录", { exact: true })).toBeVisible();
    await expect(page.getByText(/MID \d+/)).toBeVisible();
  });

  test("立即同步按钮可点击且请求成功完成", async ({ page }) => {
    await login(page);
    const syncBtn = page.getByRole("button", { name: "立即执行完整同步" });
    await expect(syncBtn).toBeEnabled();
    const syncDone = page.waitForResponse(
      (res) => res.url().includes("/api/v1/bilibili/sync/run") && res.request().method() === "POST",
      { timeout: 15_000 },
    );
    await syncBtn.click();
    const response = await syncDone;
    expect(response.status(), "sync endpoint must respond 200 after the fix").toBe(200);
    // 按钮从「同步中…」恢复为「立即同步」。
    await expect(syncBtn).toBeEnabled({ timeout: 15_000 });
    await expect(syncBtn).toHaveText(/立即同步/);
  });
});
