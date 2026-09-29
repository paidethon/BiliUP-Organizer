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

async function openReview(page: import("@playwright/test").Page) {
  await login(page);
  await page.goto("/review");
  await expect(page.getByRole("button", { name: "待审核" })).toHaveAttribute("aria-pressed", "true");
}

test.describe("AI 审核", () => {
  test("待审队列 ≥ 1 条且显示置信度进度条", async ({ page }) => {
    await openReview(page);
    await expect(page.getByText(/待审 \d+ 条/)).toBeVisible();
    const bars = page.getByRole("progressbar", { name: /置信度/ });
    await expect(bars.first()).toBeVisible();
    expect(await bars.count()).toBeGreaterThanOrEqual(1);
    // demo 种子：两条待审建议（老师好我叫何同学 / 敬汉卿）
    await expect(page.getByRole("row", { name: /老师好我叫何同学/ })).toBeVisible();
  });

  test("单条通过后移出待审并出现在已通过 tab", async ({ page }) => {
    await openReview(page);
    await page.getByRole("button", { name: "通过 老师好我叫何同学 的建议" }).click();
    await expect(page.getByRole("status").filter({ hasText: "已通过 1 条建议" })).toBeVisible();
    await expect(page.getByRole("row", { name: /老师好我叫何同学/ })).toHaveCount(0);
    // 切到已通过 tab 可见
    await page.getByRole("button", { name: "已通过", exact: true }).click();
    const acceptedRow = page.getByRole("row", { name: /老师好我叫何同学/ });
    await expect(acceptedRow).toBeVisible();
    await expect(acceptedRow).toContainText("已通过");
  });

  test("运行 AI 分类按钮点击后完成（demo 不触网）", async ({ page }) => {
    await openReview(page);
    const runBtn = page.getByRole("button", { name: "运行 AI 分类" });
    await runBtn.click();
    await expect(page.getByRole("status").filter({ hasText: "AI 分类完成" })).toBeVisible({
      timeout: 15_000,
    });
    await expect(runBtn).toBeEnabled();
    await expect(page.getByRole("alert")).toHaveCount(0);
  });
});
