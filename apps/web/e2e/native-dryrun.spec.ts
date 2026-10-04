import { expect, test, type Page } from "@playwright/test";

/** demo 模式任意凭据可登录；登录才会下发 CSRF cookie，POST 类操作必须先登录。 */
async function login(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("用户名").fill("e2e");
  await page.getByLabel("密码").fill("e2e-demo");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page).toHaveURL("/");
}

// Native-group sync is preview-first with three explicit levels:
// append (non-destructive default), replace (managed scope only) and
// managed-scope rebuild. Every write runs as a tracked background task.

test("原生分组追加同步：预览 → 后台任务确认按钮出现", async ({ page }) => {
  await login(page);
  await page.goto("/");
  const preview = page.getByRole("button", { name: "预览追加同步（推荐）" });
  await expect(preview).toBeVisible();
  await preview.click();

  await expect(page.getByText(/追加计划（R ∪ D/)).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole("button", { name: "执行同步（后台任务）" })).toBeVisible();

  // 预览阶段不得出现"成功"文案，也不得自动提交
  await expect(page.getByText("同步任务已提交")).toHaveCount(0);
});

test("原生分组替换同步：预览标注托管范围语义", async ({ page }) => {
  await login(page);
  await page.goto("/");
  await page.getByRole("button", { name: "预览替换同步" }).click();
  await expect(page.getByText(/替换计划（托管范围内/)).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText(/未托管分组保留/)).toBeVisible();
});

test("重建托管标签：Dry Run 显示保护列表，远端写入需确认", async ({ page }) => {
  await login(page);
  await page.goto("/");
  await page.getByRole("button", { name: "重建托管标签（Dry Run）" }).click();
  await expect(page.getByText(/托管范围重建计划/)).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole("button", { name: "确认重建" })).toBeVisible();
  await expect(page.getByText(/未托管的远端分组不会被删除|按本地分组重建/).first()).toBeVisible();
});
