import { expect, test, type Page } from "@playwright/test";

/** demo 模式任意凭据可登录；CSRF cookie 由后端下发、前端自动携带。 */
export async function login(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("用户名").fill("e2e");
  await page.getByLabel("密码").fill("e2e-demo");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible();
}

test.describe("周报：自然周、归档、修订", () => {
  test("日期选择定位自然周，同一周内任意日期归一到同一份周报", async ({ page }) => {
    await login(page);
    await page.goto("/weekly-report");
    await expect(page.getByRole("heading", { name: "周报" })).toBeVisible();

    // 选择同一周内的两个日期 -> 均显示同一自然周区间（周一起始）
    await page.getByLabel("选择日期定位所在周").fill("2026-03-04");
    await expect(page.getByText(/^2026-03-02 ~ 2026-03-08/)).toBeVisible();
    await page.getByLabel("选择日期定位所在周").fill("2026-03-08");
    await expect(page.getByText(/^2026-03-02 ~ 2026-03-08/)).toBeVisible();
  });

  test("上一周导航写入 URL，刷新后状态恢复", async ({ page }) => {
    await login(page);
    await page.goto("/weekly-report");
    await page.getByRole("button", { name: "上一周" }).click();
    await expect(page).toHaveURL(/date=\d{4}-\d{2}-\d{2}/);
    const urlWithDate = page.url();
    await page.reload();
    expect(page.url()).toBe(urlWithDate);
    await expect(page.getByRole("heading", { name: "周报" })).toBeVisible();
  });

  test("生成并保存后进入存档，可重新生成新修订并导出", async ({ page }) => {
    await login(page);
    await page.goto("/weekly-report");

    await page.getByRole("button", { name: "生成并保存" }).click();
    await expect(page.getByText(/已保存周报 r\d+/)).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(/正在查看存档修订/)).toBeVisible();

    await page.getByRole("button", { name: "重新生成（新修订）" }).click();
    await expect(page.getByText(/已创建新修订 r\d+/)).toBeVisible({ timeout: 20_000 });

    for (const fmt of ["HTML", "MD", "JSON"]) {
      await expect(page.getByRole("link", { name: fmt })).toBeVisible();
    }
  });

  test("四个分组标签页均渲染，图表可放大并可 Esc 关闭", async ({ page }) => {
    await login(page);
    await page.goto("/weekly-report");
    for (const tab of ["概览", "习惯", "UP 与分组", "进阶"]) {
      await expect(page.getByRole("tab", { name: tab })).toBeVisible();
    }
    await page.getByRole("tab", { name: "习惯" }).click();
    const heat = page.getByRole("img", { name: "图表：星期 × 小时观看热力图" });
    await expect(heat).toBeVisible({ timeout: 20_000 });

    await page.getByRole("tab", { name: "概览" }).click();
    const canvas = page.getByRole("img", { name: "图表：每日观看" });
    await expect(canvas).toBeVisible({ timeout: 20_000 });
    await page.getByRole("button", { name: "放大", exact: true }).first().click();
    const dialog = page.getByRole("dialog", { name: /每日观看（放大）/ });
    await expect(dialog).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
  });
});
