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

test.describe("认证与登录态", () => {
  test("登录页渲染标题、表单与 demo 提示", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: /BiliUP/ })).toBeVisible();
    await expect(page.getByText("登录以继续")).toBeVisible();
    await expect(page.getByLabel("用户名")).toBeVisible();
    await expect(page.getByLabel("密码")).toBeVisible();
    await expect(page.getByRole("button", { name: "登录" })).toBeVisible();
    await expect(page.getByText("演示模式：任意用户名密码均可登录")).toBeVisible();
  });

  test("demo 登录成功跳转 / 并显示侧栏导航", async ({ page }) => {
    await login(page);
    await expect(page).toHaveURL("/");
    // 限定在主导航内，避免与页面内「前往××」快捷链接重名
    const nav = page.getByRole("navigation", { name: "主导航" });
    // 移动端导航条不含「设置」chip 之外的所有桌面项？——八个项都在，逐个校验
    for (const label of ["仪表盘", "关注管理", "本地分组", "AI 审核", "提醒中心", "观看历史", "周报", "设置"]) {
      await expect(nav.getByRole("link", { name: label })).toBeVisible();
    }
    // 演示模式徽标：桌面在侧栏（complementary），移动端在顶部状态条
    await expect(page.getByText("演示模式", { exact: true }).first()).toBeVisible();
  });

  test("登出按钮回到登录页", async ({ page }) => {
    await login(page);
    await page.getByRole("button", { name: "退出登录" }).click();
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("button", { name: "登录" })).toBeVisible();
    await expect(page.getByText("演示模式：任意用户名密码均可登录")).toBeVisible();
  });
});
