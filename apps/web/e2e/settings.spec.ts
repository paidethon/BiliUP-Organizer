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

const SECTIONS = ["AI 分类", "邮件（SMTP）", "LumiRSS", "提醒阈值", "同步"];

async function openSettings(page: import("@playwright/test").Page) {
  await login(page);
  await page.goto("/settings");
  for (const name of SECTIONS) {
    await expect(page.getByRole("region", { name })).toBeVisible();
  }
}

test.describe("设置", () => {
  test("五个分区折叠卡可见且默认收起", async ({ page }) => {
    await openSettings(page);
    for (const name of SECTIONS) {
      const region = page.getByRole("region", { name });
      await expect(region.getByRole("button", { expanded: false })).toBeVisible();
    }
  });

  test("提醒区改断更天数为 45 并保存成功", async ({ page }) => {
    await openSettings(page);
    const region = page.getByRole("region", { name: "提醒阈值" });
    await region.getByRole("button", { expanded: false }).click();
    const staleDays = region.getByLabel("断更天数阈值");
    await staleDays.fill("45");
    await region.getByRole("button", { name: "保存提醒阈值" }).click();
    await expect(region.getByRole("status").filter({ hasText: "已保存" })).toBeVisible();
    // 重新加载后持久生效
    await page.reload();
    const region2 = page.getByRole("region", { name: "提醒阈值" });
    await region2.getByRole("button", { expanded: false }).click();
    await expect(region2.getByLabel("断更天数阈值")).toHaveValue("45");
  });

  test("AI 测试连接返回 demo 提示", async ({ page }) => {
    await openSettings(page);
    const region = page.getByRole("region", { name: "AI 分类" });
    await region.getByRole("button", { expanded: false }).click();
    await region.getByRole("button", { name: "测试连接" }).click();
    await expect(region.getByText(/demo mode: integration test skipped/)).toBeVisible({
      timeout: 10_000,
    });
  });
});
