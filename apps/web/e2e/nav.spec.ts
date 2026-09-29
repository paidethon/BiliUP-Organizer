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

const NAV = [
  { label: "仪表盘", path: "/" },
  { label: "关注管理", path: "/followings" },
  { label: "本地分组", path: "/groups" },
  { label: "AI 审核", path: "/review" },
  { label: "提醒中心", path: "/reminders" },
  { label: "观看历史", path: "/history" },
  { label: "每周周报", path: "/weekly-report" },
  { label: "设置", path: "/settings" },
];

test.describe("全局导航", () => {
  test("8 个导航项逐个点击无 404 / pageerror / console error", async ({ page }) => {
    const consoleErrors: string[] = [];
    const badResponses: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(`[${page.url()}] ${msg.text()}`);
    });
    page.on("pageerror", (err) => consoleErrors.push(`pageerror: ${err.message}`));
    page.on("response", (res) => {
      // favicon 缺失不算业务错误
      if (res.status() >= 400 && !res.url().includes("favicon")) {
        badResponses.push(`${res.status()} ${res.url()}`);
      }
    });

    await login(page);
    const nav = page.getByRole("navigation", { name: "主导航" });
    for (const item of NAV) {
      await nav.getByRole("link", { name: item.label }).click();
      await expect(page).toHaveURL(`http://127.0.0.1:8067${item.path}`);
      await expect(page.getByRole("heading", { name: item.label, level: 1 })).toBeVisible();
    }

    expect(badResponses, "不应有 4xx/5xx 响应").toEqual([]);
    expect(consoleErrors, "不应有 console error / pageerror").toEqual([]);
  });
});
