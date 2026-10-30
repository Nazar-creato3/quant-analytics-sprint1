import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { assertNoSeriousAxe, openAuthed } from "./helpers/shell";

test.describe("portfolio report page", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("first screen shows API numbers and empty states", async ({ page }) => {
    await openAuthed(page, "/portfolio-report");
    await expect(page.getByTestId("portfolio-report")).toBeVisible();
    await expect(page.getByTestId("report-TWR")).toHaveText("нет данных");
    await expect(page.getByTestId("report-equity-vs-bench")).toHaveText("нет данных");
    const dir = resolve(process.cwd(), "../docs/qa/reports/20-screenshots");
    mkdirSync(dir, { recursive: true });
    await page.screenshot({ path: resolve(dir, "report-empty.png"), animations: "disabled" });
    await assertNoSeriousAxe(page, "portfolio-report");
  });
});
