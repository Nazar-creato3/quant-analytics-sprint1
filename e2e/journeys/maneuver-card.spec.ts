import { expect, test } from "@playwright/test";
import { assertNoSeriousAxe, openLive, saveLiveProfile, waitForLivePropose } from "./helpers/shell";

test.describe("maneuver card", () => {
  test("act page shows live maneuver impact or the missing-data reason", async ({ page }) => {
    test.setTimeout(300_000);
    await openLive(page, "/act");
    const proposedPromise = waitForLivePropose(page);
    expect((await saveLiveProfile(page)).status()).toBe(200);
    const proposed = await proposedPromise;
    const body = await proposed.json();
    expect(body.target_source).toBe("user");
    const items = (body.items || []) as Array<{ impact?: { delta?: Record<string, { before?: string; after?: string }> } }>;
    if (items.length === 0) {
      await expect(page.getByTestId("act-skipped")).toBeVisible();
      const skipped = (body.skipped || []) as Array<{ reason?: string }>;
      expect(skipped.length).toBeGreaterThan(0);
      await expect(page.getByTestId("act-skipped")).toContainText(String(skipped[0].reason || "нет данных"));
    } else {
      const card = page.getByTestId("maneuver-card").first();
      await expect(card).toBeVisible();
      const hhi = items[0].impact?.delta?.hhi;
      if (hhi) {
        await expect(card).toContainText(`hhi: ${hhi.before} → ${hhi.after}`);
      }
    }
    await assertNoSeriousAxe(page, "maneuver-card");
  });
});
