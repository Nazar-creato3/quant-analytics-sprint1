import { expect, test } from "@playwright/test";
import { openAuthed } from "./helpers/shell";

test.describe("sandbox lawyer flags off", () => {
  test("sandbox page stays hidden behind flag", async ({ page }) => {
    await openAuthed(page, "/sandbox");
    await expect(page.getByTestId("sandbox-page")).toBeVisible();
    await page.getByTestId("sandbox-run").click();
    await expect(page.getByText(/флаг выключен/)).toBeVisible();
  });
});
