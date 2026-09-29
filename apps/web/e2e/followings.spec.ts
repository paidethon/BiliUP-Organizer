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

async function openFollowings(page: import("@playwright/test").Page) {
  await login(page);
  await page.goto("/followings");
  // 全量加载完成（demo 种子共 24 个 UP 主）
  await expect(page.getByText("共 24 个 UP 主")).toBeVisible();
}

test.describe("关注管理", () => {
  test("表格展示全部关注，行数 ≥ 20", async ({ page }) => {
    await openFollowings(page);
    const rows = page.getByRole("row");
    const count = await rows.count();
    expect(count).toBeGreaterThanOrEqual(21); // 24 数据行 + 1 表头
    // 分页控件存在
    await expect(page.getByRole("button", { name: "上一页" })).toBeVisible();
    await expect(page.getByRole("button", { name: "下一页" })).toBeVisible();
    await expect(page.getByText(/第 1 \/ \d+ 页/)).toBeVisible();
  });

  test("搜索「何同学」过滤出 2 行", async ({ page }) => {
    await openFollowings(page);
    await page.getByLabel("搜索 UP 主").fill("何同学");
    await expect(page.getByText("共 2 个 UP 主")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByRole("row", { name: /何同学/ })).toHaveCount(2);
  });

  test("筛选从未观看后仅剩 watched=0 的 UP", async ({ page }) => {
    await openFollowings(page);
    await page.getByLabel("按状态筛选").selectOption({ label: "从未观看" });
    await expect(page.getByText("共 3 个 UP 主")).toBeVisible();
    const names = ["吕永汉", "早睡早起冠军", "新关注的UP"];
    for (const name of names) {
      const row = page.getByRole("row", { name: new RegExp(name) });
      await expect(row).toBeVisible();
      // 第 6 列「已看」必须为 0
      await expect(row.getByRole("cell").nth(5)).toHaveText("0");
    }
    await expect(page.getByRole("row", { name: /何同学/ })).toHaveCount(0);
  });

  test("勾选 2 行批量移动到知识科普，组 Badge 更新", async ({ page }) => {
    await openFollowings(page);
    await page.getByLabel("选择 何同学").check();
    await page.getByLabel("选择 老师好我叫何同学").check();
    const bar = page.getByRole("toolbar", { name: "已选中 2 个 UP 的批量操作" });
    await expect(bar).toBeVisible();
    await bar.getByLabel("选择目标分组").selectOption({ label: "知识科普" });
    await bar.getByRole("button", { name: "确认移动到所选分组" }).click();
    await expect(page.getByRole("status").filter({ hasText: "已更新 2 个 UP 主" })).toBeVisible();
    // 行内分组 Badge 更新为知识科普
    await expect(
      page.getByRole("row", { name: /何同学/ }).filter({ hasText: "知识科普" }),
    ).toHaveCount(2);
  });
});
