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

async function openReminders(page: Page) {
  await login(page);
  await page.goto("/reminders");
  await expect(page.getByRole("button", { name: "未读", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  const list = page.getByRole("list", { name: "提醒列表" });
  await expect(list).toBeAttached();
  return list;
}

test.describe("提醒中心", () => {
  test("未读列表 ≥ 1 条，含断更与从未观看文案", async ({ page }) => {
    const list = await openReminders(page);
    // demo 种子含 2 条开放提醒（断更 / 从未观看）；共享库下只断言 ≥1
    await expect(page.getByText(/当前视图 \d+ 条/)).toBeVisible();
    const open = list.getByRole("listitem");
    const count = await open.count();
    expect(count).toBeGreaterThanOrEqual(1);
    await expect(page.getByText(/已 \d+ 天未更新/)).toBeVisible();
    await expect(page.getByText("从未观看").first()).toBeVisible();
  });

  test("单条标记已读后从未读列表消失", async ({ page }) => {
    const list = await openReminders(page);
    const item = list.getByRole("listitem").filter({ hasText: /已 \d+ 天未更新/ });
    await item.getByRole("button", { name: /标记已读：/ }).click();
    await expect(page.getByRole("status").filter({ hasText: "已标记为已读" })).toBeVisible();
    await expect(list.getByRole("listitem").filter({ hasText: /已 \d+ 天未更新/ })).toHaveCount(0);
  });

  test("全部已读后显示空态", async ({ page }) => {
    const list = await openReminders(page);
    await page.getByRole("button", { name: "全部标记已读" }).click();
    await expect(page.getByRole("status").filter({ hasText: /已全部标记已读/ })).toBeVisible();
    await expect(list.getByRole("listitem")).toHaveCount(0);
    await expect(page.getByText("没有提醒")).toBeVisible();
  });

  test("已读 tab 可见已读项", async ({ page }) => {
    await openReminders(page);
    // 前置：清空未读（独立可跑；重复点击幂等）
    await page.getByRole("button", { name: "全部标记已读" }).click();
    await expect(page.getByRole("status").filter({ hasText: /已全部标记已读/ })).toBeVisible();
    await page.getByRole("button", { name: "已读", exact: true }).click();
    const acked = page.getByRole("list", { name: "提醒列表" }).getByRole("listitem");
    await expect(acked.first()).toBeVisible();
    const ackedCount = await acked.count();
    expect(ackedCount).toBeGreaterThanOrEqual(1);
    await expect(acked.first()).toContainText("（已读）");
  });
});
