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

test.describe("每周周报", () => {
  test("预览容器存在，生成预览后 HTML 含「周报」", async ({ page }) => {
    await login(page);
    await page.goto("/weekly-report");
    await expect(page.getByRole("heading", { name: "每周周报" })).toBeVisible();
    // 应用内唯一的 iframe 预览容器（初始可能显示空态）
    const iframe = page.locator("iframe");
    await page.getByRole("button", { name: "生成周报预览" }).click();
    await expect(iframe).toBeVisible();
    await expect(page.getByText(/预览生成于/)).toBeVisible();
    // srcDoc 内容为后端生成的周报 HTML，标题包含「周报」
    const inner = page.frameLocator("iframe");
    await expect(inner.getByRole("heading", { level: 1 })).toContainText("周报");
  });
});
