import { expect, test } from "@playwright/test";
import { assertNoSeriousAxe, openLive, saveLiveProfile } from "./helpers/shell";

test.describe("investment profile", () => {
  test("questionnaire saves limits against the live API and has no serious axe", async ({ page }) => {
    test.setTimeout(300_000);
    await openLive(page, "/account");
    const response = await saveLiveProfile(page);
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body.limits.var_95).toBe("0.050");
    expect(body.limits.es_975).toBe("0.070");
    expect(body.limits.max_drawdown).toBe("0.150");
    await expect(page.getByTestId("profile-limits")).toContainText("VaR 0.050", { timeout: 15_000 });
    await assertNoSeriousAxe(page, "investment-profile");
  });
});
