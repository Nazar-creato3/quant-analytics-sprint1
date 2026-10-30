import { expect, test } from "@playwright/test";
import { openAuthed } from "./helpers/shell";

test.describe("screener", () => {
  test("shows нет данных instead of zero and cycle links", async ({ page }) => {
    await openAuthed(page, "/screener");
    await page.route("**/api/v1/market/screener**", async (route) => {
      if (route.request().url().includes("/saved") || route.request().url().includes("/export")) {
        await route.fulfill({ json: { items: [] } });
        return;
      }
      await route.fulfill({
        json: {
          items: [
            {
              symbol: "SBER",
              name: "Сбербанк",
              pe: null,
              pe_status: "нет данных",
              beta: 1.05,
              es_975: 0.06,
              fundamentals_source: "catalog_golden",
              fundamentals_as_of: "2026-09-30",
            },
          ],
          count: 1,
          source: "catalog",
        },
      });
    });
    await page.goto("/screener", { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("screener-pe").first()).toContainText("—");
    await expect(page.getByTestId("cross-actions").first()).toBeVisible();
  });
});
