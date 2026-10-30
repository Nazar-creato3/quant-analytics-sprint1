import { expect, test } from "@playwright/test";
import { openAuthed } from "./helpers/shell";

test.describe("quotes and charts", () => {
  test("markets quotes show freshness labels", async ({ page }) => {
    await openAuthed(page, "/markets");
    await page.route("**/api/v1/market/overview**", async (route) => {
      await route.fulfill({
        json: {
          groups: {
            us_equity: [
              {
                symbol: "SPY",
                name: "S&P 500",
                price: 500,
                change_pct: 0.1,
                freshness_label: "с задержкой 15 минут",
                license_tag: "internal_only",
                display_allowed: true,
              },
            ],
          },
          coverage: 1,
          regime: "range",
          news: [],
          macro: [],
          compare: {},
          fx_matrix: [],
        },
      });
    });
    await page.goto("/markets", { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("paper-live-badge")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("quote-freshness").first()).toContainText("с задержкой");
  });
});
