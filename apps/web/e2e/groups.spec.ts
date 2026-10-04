import { expect, test, type Locator, type Page } from "@playwright/test";

/** demo 模式任意凭据可登录；CSRF cookie 由后端下发、前端自动携带。 */
async function login(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("用户名").fill("e2e");
  await page.getByLabel("密码").fill("e2e-demo");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible();
}

const GROUP_NAME = "E2E测试组";
const GROUP_COLOR = "#34d399";
const GROUP_DESC = "E2E 修改后的描述文案";

async function openGroups(page: Page) {
  await login(page);
  await page.goto("/groups");
  const list = page.getByRole("list", { name: "分组列表" });
  await expect(list).toBeVisible();
  return list;
}

/** 共享 demo DB：同名分组已存在（本文件其他用例创建）时直接复用，否则新建。 */
async function ensureGroup(page: Page, list: Locator) {
  const existing = list.getByRole("listitem").filter({ hasText: GROUP_NAME });
  if ((await existing.count()) > 0) {
    await expect(existing.first()).toBeVisible();
    return;
  }
  await page.getByRole("button", { name: "新建分组" }).click();
  const dialog = page.getByRole("dialog", { name: "新建分组" });
  await dialog.getByLabel("分组名称").fill(GROUP_NAME);
  await dialog.getByRole("button", { name: "创建分组" }).click();
  await expect(dialog).toBeHidden();
  await expect(list.getByRole("listitem").filter({ hasText: GROUP_NAME })).toBeVisible();
}

test.describe("本地分组", () => {
  test("分组卡片网格显示预置分组科技数码", async ({ page }) => {
    const list = await openGroups(page);
    await expect(page.getByText(/共 \d+ 个分组/)).toBeVisible();
    await expect(list.getByRole("heading", { name: "科技数码" })).toBeVisible();
    await expect(list.getByRole("listitem")).toHaveCount(8); // demo 种子 8 个分组
  });

  test("新建分组（名称+选色）后出现在列表", async ({ page }) => {
    const list = await openGroups(page);
    await page.getByRole("button", { name: "新建分组" }).click();
    const dialog = page.getByRole("dialog", { name: "新建分组" });
    await expect(dialog).toBeVisible();
    await dialog.getByLabel("分组名称").fill(GROUP_NAME);
    const colorBtn = dialog.getByRole("button", { name: `选择颜色 ${GROUP_COLOR}` });
    await colorBtn.click();
    await expect(colorBtn).toHaveAttribute("aria-pressed", "true");
    await dialog.getByRole("button", { name: "创建分组" }).click();
    await expect(dialog).toBeHidden();
    await expect(list.getByRole("listitem").filter({ hasText: GROUP_NAME })).toBeVisible();
  });

  test("编辑分组描述并保存生效", async ({ page }) => {
    const list = await openGroups(page);
    await ensureGroup(page, list);

    await list.getByRole("button", { name: `编辑分组 ${GROUP_NAME}` }).click();
    const dialog = page.getByRole("dialog", { name: `编辑分组：${GROUP_NAME}` });
    await expect(dialog).toBeVisible();
    await dialog.getByLabel("分组描述").fill(GROUP_DESC);
    await dialog.getByRole("button", { name: "保存修改" }).click();
    await expect(dialog).toBeHidden();
    await expect(list.getByRole("listitem").filter({ hasText: GROUP_DESC })).toBeVisible();
  });

  test("删除分组后从列表消失", async ({ page }) => {
    const list = await openGroups(page);
    await ensureGroup(page, list);

    await list.getByRole("button", { name: `删除分组 ${GROUP_NAME}` }).click();
    const dialog = page.getByRole("dialog", { name: "删除分组" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText(GROUP_NAME)).toBeVisible();
    await dialog.getByRole("button", { name: `确认删除分组 ${GROUP_NAME}` }).click();
    await expect(dialog).toBeHidden();
    await expect(list.getByRole("listitem").filter({ hasText: GROUP_NAME })).toHaveCount(0);
  });
});
