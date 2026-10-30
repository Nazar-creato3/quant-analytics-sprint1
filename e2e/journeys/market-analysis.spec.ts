import { expect, test } from "@playwright/test";
import { openAuthed } from "./helpers/shell";

test.describe("market analysis", () => {
  test("shows regime text and calendar нет данных", async ({ page }) => {
    await openAuthed(page, "/markets");
    await page.route("**/api/v1/market/analysis**", async (route) => {
      await route.fulfill({
        json: {
          regime: { label: "trend_up", source: "market_regime" },
          text: { phrase: "Режим рынка trend_up, волатильность 0.0120.", source: "explanations" },
          calendar: { data_status: "нет данных", events: [] },
          source: "market_analysis",
        },
      });
    });
    await page.goto("/markets", { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("market-analysis")).toBeVisible();
    await expect(page.getByTestId("market-regime-label")).toContainText("trend_up");
    await expect(page.getByTestId("market-calendar-status")).toContainText("нет данных");
    await expect(page.getByTestId("cross-actions").first()).toBeVisible();
  });
});
