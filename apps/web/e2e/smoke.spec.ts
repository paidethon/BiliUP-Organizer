import { expect, test } from "@playwright/test";

test("demo mode: login lands on dashboard", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("用户名").fill("demo");
  await page.getByLabel("密码").fill("demo");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("link", { name: "仪表盘" })).toBeVisible();
});
