import { expect, test, type Page } from "@playwright/test";

/** demo 模式任意凭据可登录；登录才会下发 CSRF cookie，POST 类操作必须先登录。 */
async function login(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("用户名").fill("e2e");
  await page.getByLabel("密码").fill("e2e-demo");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page).toHaveURL("/");
}

// Full-library classification job lifecycle in demo mode: create → progress →
// completion survives a page reload; retry failures when present.

test("创建全量分类任务并显示进度与完成状态", async ({ page }) => {
  await login(page);
  await page.goto("/review");
  await expect(page.getByRole("heading", { name: /AI/ })).toBeVisible();

  // confirm dialog must have its handler registered before the click
  page.on("dialog", (dialog) => void dialog.accept());
  const fullButton = page.getByRole("button", { name: "重新分类全部" });
  if (await fullButton.isVisible().catch(() => false)) {
    await fullButton.click();
  }
  // job panel shows the running or already-completed job with counters
  await expect(page.getByText(/总数|进度/).first()).toBeVisible({ timeout: 10_000 });
  // demo jobs finish quickly; the panel must show a terminal state
  await expect(page.getByText(/已完成|已取消|已暂停|失败/).first()).toBeVisible({ timeout: 20_000 });
});

test("页面刷新后任务状态仍在", async ({ page }) => {
  await login(page);
  await page.goto("/review");
  page.on("dialog", (dialog) => void dialog.accept());
  const create = page.getByRole("button", { name: "重新分类全部" });
  if (await create.isVisible().catch(() => false)) {
    await create.click();
  }
  await expect(page.getByText(/总数|进度/).first()).toBeVisible({ timeout: 10_000 });
  await page.reload();
  // the job panel still reflects the (finished) job instead of showing nothing
  await expect(page.getByText(/总数|进度/).first()).toBeVisible({ timeout: 10_000 });
});

test("失败项可重试", async ({ page }) => {
  await login(page);
  await page.goto("/review");
  page.on("dialog", (dialog) => void dialog.accept());
  const create = page.getByRole("button", { name: "重新分类全部" });
  if (await create.isVisible().catch(() => false)) {
    await create.click();
  }
  await expect(page.getByText(/总数|进度/).first()).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText(/已完成|失败/).first()).toBeVisible({ timeout: 20_000 });
  const retry = page.getByRole("button", { name: /重试失败/ });
  if (await retry.isVisible().catch(() => false)) {
    await retry.click();
    await expect(page.getByText(/已完成/).first()).toBeVisible({ timeout: 20_000 });
  }
});
