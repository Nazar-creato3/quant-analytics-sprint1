import { expect, test } from "@playwright/test";
import {
  CYCLE_PAGES,
  assertNoSeriousAxe,
  openAuthed,
  snapCyclePage,
} from "./helpers/shell";

test.describe("IA cycle shell", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("walks узнать → оценить → риск → действовать → контролировать with paper/live", async ({
    page,
  }) => {
    await openAuthed(page, CYCLE_PAGES[0].href);
    await expect(page.getByTestId("ia-cycle-schema")).toContainText("Узнать");
    await expect(page.getByTestId("ia-cycle-schema")).toContainText("Оценить");
    await expect(page.getByTestId("ia-cycle-schema")).toContainText("Проверить риск");
    await expect(page.getByTestId("ia-cycle-schema")).toContainText("Действовать");
    await expect(page.getByTestId("ia-cycle-schema")).toContainText("Контролировать");

    const badge = page.getByTestId("paper-live-badge");
    await expect(badge.getByRole("button", { name: "paper" })).toHaveAttribute("aria-pressed", "true");

    for (const step of CYCLE_PAGES) {
      await page.goto(step.href, { waitUntil: "domcontentloaded" });
      await expect(page.getByTestId("paper-live-badge")).toBeVisible({ timeout: 20_000 });
      await snapCyclePage(page, `${step.id}-paper`);
    }

    await badge.getByRole("button", { name: "live" }).click();
    await expect(badge.getByRole("button", { name: "live" })).toHaveAttribute("aria-pressed", "true");
    await page.goto("/portfolio-report", { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("paper-live-badge").getByRole("button", { name: "live" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await snapCyclePage(page, "risk-live");
  });

  for (const step of CYCLE_PAGES) {
    test(`axe serious/critical = 0 on ${step.id} (${step.href})`, async ({ page }) => {
      await openAuthed(page, step.href);
      await assertNoSeriousAxe(page, step.href);
    });
  }
});
