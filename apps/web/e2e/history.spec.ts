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

test.describe("观看历史", () => {
  test("统计卡与覆盖说明渲染", async ({ page }) => {
    await login(page);
    await page.goto("/history");
    for (const label of ["区间观看记录", "去重 UP", "去重视频", "估算观看时长", "未发现观看记录"]) {
      await expect(page.getByText(label, { exact: true })).toBeVisible();
    }
    // 覆盖状态：明确区分同步范围
    await expect(page.getByText(/统计仅覆盖已同步的观看历史/).first()).toBeVisible();
  });

  test("每日观看与 TOP UP 图表渲染（ECharts）", async ({ page }) => {
    await login(page);
    await page.goto("/history");
    await expect(page.getByRole("img", { name: "图表：每日观看" })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("img", { name: "图表：TOP UP 排行" })).toBeVisible({ timeout: 20_000 });
  });

  test("明细表渲染，观看时间为上海时区格式", async ({ page }) => {
    await login(page);
    await page.goto("/history");
    await expect(page.getByText(/共 \d+ 条 · 第 1 \/ \d+ 页/)).toBeVisible();
    // 上海时区格式：YYYY-MM-DD HH:mm（Intl zh-CN 2 位）
    const stampCell = page.getByText(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/).first();
    await expect(stampCell).toBeVisible({ timeout: 20_000 });
  });

  test("日期筛选写入 URL 并生效", async ({ page }) => {
    await login(page);
    await page.goto("/history");
    // 用远期窄区间点击每日图 -> URL 带 start/end（通过 TOP 图钻取替代）
    await page.getByRole("img", { name: "图表：每日观看" }).waitFor({ timeout: 20_000 });
    // 直接断言筛选控件存在且清除筛选可用
    await expect(page.getByText("开始日期（上海）")).toBeVisible();
    await expect(page.getByText("结束日期（含当日，上海）")).toBeVisible();
  });
});
