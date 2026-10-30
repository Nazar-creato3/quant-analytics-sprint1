import { expect, test } from "@playwright/test";
import { assertNoSeriousAxe } from "./helpers/shell";

const PAGES = [
  { path: "/site", heading: "Quant Analytics" },
  { path: "/methodology", heading: "Методика" },
  { path: "/site/accuracy", heading: "Точность прогнозов" },
  { path: "/legal/consent", heading: "Согласие на обработку" },
];

test.describe("public site without auth", () => {
  for (const pageInfo of PAGES) {
    test(`${pageInfo.path} renders unpublished copy`, async ({ page }) => {
      await page.goto(pageInfo.path, { waitUntil: "domcontentloaded" });
      await expect(page.getByRole("heading", { level: 1 })).toContainText(pageInfo.heading);
      await expect(page.getByText(/ожидает текста|нет данных|не опубликован/i).first()).toBeVisible();
      await expect(page).not.toHaveURL(/\/login/);
    });

    test(`axe serious/critical = 0 on ${pageInfo.path}`, async ({ page }) => {
      await page.goto(pageInfo.path, { waitUntil: "domcontentloaded" });
      await assertNoSeriousAxe(page, pageInfo.path);
    });
  }

  test("sitemap and robots are public", async ({ request }) => {
    const robots = await request.get("/robots.txt");
    expect(robots.ok()).toBeTruthy();
    const robotsText = await robots.text();
    expect(robotsText).toContain("/site");
    expect(robotsText).toContain("Disallow: /account");
    const sitemap = await request.get("/sitemap.xml");
    expect(sitemap.ok()).toBeTruthy();
    const xml = await sitemap.text();
    expect(xml).toContain("/site");
    expect(xml).not.toContain("/account");
  });
});
