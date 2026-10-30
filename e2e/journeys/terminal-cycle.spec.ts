import { expect, test } from "@playwright/test";
import { openAuthed } from "./helpers/shell";

test.describe("terminal cycle", () => {
  test("news → paper → portfolio → risk check → maneuvers, same symbol", async ({ page }) => {
    await openAuthed(page, "/markets");
    await page.route("**/api/v1/market/overview**", async (route) => {
      await route.fulfill({
        json: {
          groups: {},
          news: [
            {
              title: "Сбербанк объявил дивиденды",
              url: "https://example.test/sber",
              tickers: ["SBER"],
            },
          ],
          coverage: 6,
          source: "test",
        },
      });
    });
    await page.route("**/api/v1/market/analysis**", async (route) => {
      await route.fulfill({
        json: {
          regime: { label: "range", source: "market_regime" },
          calendar: { data_status: "нет данных" },
          text: { phrase: "Режим рынка range, волатильность 0.0100." },
        },
      });
    });
    await page.goto("/markets", { waitUntil: "domcontentloaded" });
    const newsActions = page.getByTestId("market-news-item").getByTestId("cross-actions").first();
    await expect(newsActions).toBeVisible();
    await newsActions.getByRole("button", { name: /Действия/ }).click();
    await newsActions.getByTestId("cross-portfolio").click();
    await expect(page).toHaveURL(/portfolio\?tab=risk&add=SBER/);
    await page.getByTestId("cross-maneuvers").first().click();
    await expect(page).toHaveURL(/act\?symbol=SBER/);
    await expect(page.getByTestId("cycle-ticker")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("cross-actions").first()).toHaveAttribute("data-ticker", "SBER", { timeout: 15_000 });
  });
});
