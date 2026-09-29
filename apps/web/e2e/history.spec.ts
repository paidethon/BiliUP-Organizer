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
  test("统计卡四张全部渲染", async ({ page }) => {
    await login(page);
    await page.goto("/history");
    const stats = page.getByRole("region", { name: "观看统计" });
    await expect(stats).toBeVisible();
    for (const label of ["近 30 天观看", "总记录", "涉及 UP", "从未观看"]) {
      await expect(stats.getByText(label, { exact: true })).toBeVisible();
    }
  });

  test("近 30 天柱状图容器渲染", async ({ page }) => {
    await login(page);
    await page.goto("/history");
    const chart = page.getByRole("img", { name: "近 30 天每日观看记录柱状图" });
    await expect(chart).toBeVisible();
    await expect(page.getByText(/峰值 \d+ 条 \/ 天/)).toBeVisible();
  });

  test("观看明细表至少 1 行", async ({ page }) => {
    await login(page);
    await page.goto("/history");
    const table = page.getByRole("table", { name: "观看历史明细" });
    await expect(table).toBeVisible();
    await expect(page.getByText(/共 \d+ 条 · 第 1 \/ \d+ 页/)).toBeVisible();
    const dataRows = table.getByRole("row");
    expect(await dataRows.count()).toBeGreaterThanOrEqual(2); // 表头 + ≥1 行
    await expect(table.getByRole("link", { name: /在 B 站打开/ }).first()).toBeVisible();
  });
});
