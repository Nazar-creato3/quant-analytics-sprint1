import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { assertNoSeriousAxe, openAuthed } from "./helpers/shell";

test.describe("connect capital", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("demo path opens first report", async ({ page }) => {
    await openAuthed(page, "/connect-capital");
    await expect(page.getByTestId("connect-capital")).toBeVisible();
    await page.getByTestId("try-demo").click();
    await expect(page).toHaveURL(/portfolio-report/);
    const dir = resolve(process.cwd(), "../docs/qa/reports/19-screenshots");
    mkdirSync(dir, { recursive: true });
    await page.screenshot({ path: resolve(dir, "demo-to-report.png"), animations: "disabled" });
    await assertNoSeriousAxe(page, "connect-capital-report");
  });
});
