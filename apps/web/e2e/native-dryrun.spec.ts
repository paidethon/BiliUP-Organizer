import { expect, test, type Page } from "@playwright/test";

/** demo 模式任意凭据可登录；登录才会下发 CSRF cookie，POST 类操作必须先登录。 */
async function login(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("用户名").fill("e2e");
  await page.getByLabel("密码").fill("e2e-demo");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page).toHaveURL("/");
}

// Native-group push is preview-first: the dry run shows the plan (would
// create/delete/move/skip) and only an explicit confirmation performs the
// remote write. Remote-side no-write behavior is asserted in backend tests.

test("原生分组同步支持 Dry Run 预览", async ({ page }) => {
  await login(page);
  await page.goto("/");
  const preview = page.getByRole("button", { name: "预览原生分组同步计划" });
  await expect(preview).toBeVisible();
  await preview.click();

  // plan panel appears with the preview numbers
  await expect(page.getByText(/覆盖重建计划|增量计划/)).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText(/预计创建分组/)).toBeVisible();
  await expect(page.getByText(/预计移动成员/)).toBeVisible();

  // execution stays behind an explicit confirm — do not click it here;
  // the dry run itself must not change anything (no "已按本地分组重建" note)
  await expect(page.getByText("已按本地分组重建")).toHaveCount(0);
});
