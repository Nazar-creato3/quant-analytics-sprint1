import { expect, test } from "@playwright/test";
import { openAuthed } from "./helpers/shell";

test.describe("notification center", () => {
  test("lists fixture event", async ({ page }) => {
    await openAuthed(page, "/notifications");
    await expect(page.getByTestId("notify-center")).toBeVisible();
    await expect(page.getByText("Синхронизация")).toBeVisible();
  });
});
