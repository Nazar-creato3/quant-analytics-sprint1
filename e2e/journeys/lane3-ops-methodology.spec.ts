import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { stubApis } from "./helpers/shell";

async function analyzeAxe(page: Page, route: string) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  const blocking = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  const other = results.violations.filter(
    (v) => v.impact !== "serious" && v.impact !== "critical",
  );
  // eslint-disable-next-line no-console
  console.log(
    JSON.stringify(
      {
        route,
        url: page.url(),
        title: await page.title(),
        blocking: blocking.map((v) => ({ id: v.id, impact: v.impact, help: v.help })),
        other: other.map((v) => ({ id: v.id, impact: v.impact, help: v.help })),
      },
      null,
      2,
    ),
  );
  expect(blocking, `${route} serious/critical axe`).toEqual([]);
}

test("/methodology is public and has no serious axe", async ({ page }) => {
  const response = await page.goto("/methodology", { waitUntil: "domcontentloaded" });
  expect(response?.ok(), `GET /methodology ${response?.status()}`).toBeTruthy();
  await expect(page.getByRole("heading", { name: "Методика" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Риск" })).toBeVisible();
  await expect(page.locator("body")).toContainText("нет данных");
  await analyzeAxe(page, "/methodology");
});

test("/admin/ops with session cookie has no serious axe", async ({ page }) => {
  const origin =
    process.env.E2E_BASE_URL || `http://127.0.0.1:${process.env.E2E_PORT || "3000"}`;
  await page.context().addCookies([{ name: "access_token", value: "e2e-shell", url: origin }]);
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "e2e-shell");
  });
  await stubApis(page);
  const response = await page.goto("/admin/ops", { waitUntil: "domcontentloaded" });
  expect(response?.status(), `GET /admin/ops ${response?.status()}`).toBeLessThan(400);
  await expect(page.getByRole("heading", { name: "Наблюдаемость" })).toBeVisible();
  await expect(page.locator("body")).toContainText("Бэкап: нет данных");
  await expect(page).not.toHaveURL(/\/login/);
  await analyzeAxe(page, "/admin/ops");
});
