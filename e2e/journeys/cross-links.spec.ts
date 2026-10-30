import { expect, test } from "@playwright/test";
import { openAuthed } from "./helpers/shell";

test.describe("cross links", () => {
  test("forecast risk action and command palette", async ({ page }) => {
    await openAuthed(page, "/forecasting");
    await expect(page.getByTestId("cross-actions")).toBeVisible();
    await page.getByTestId("cross-actions").getByRole("link", { name: "Проверить риск этой сделки" }).click();
    await expect(page).toHaveURL(/portfolio-risk/);
    await page.keyboard.press("Control+k");
    await expect(page.getByTestId("command-palette")).toBeVisible();
  });
});
