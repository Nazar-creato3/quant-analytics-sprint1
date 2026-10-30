import { expect, test } from "@playwright/test";
import { assertNoSeriousAxe, openLive, saveLiveProfile, waitForLivePropose } from "./helpers/shell";

async function saveProfile(page: import("@playwright/test").Page): Promise<void> {
  const response = await saveLiveProfile(page);
  expect(response.status()).toBe(200);
}

test.describe("target book", () => {
  test("act page shows the live user book and the NDFL scale", async ({ page }) => {
    test.setTimeout(300_000);
    await openLive(page, "/act");
    const proposedPromise = waitForLivePropose(page);
    await saveProfile(page);
    const proposed = await proposedPromise;
    const body = await proposed.json();
    expect(body.target_source).toBe("user");
    expect(body.target_source).not.toBe("model");
    expect(String(body.target_book?.tax?.rate || "")).toContain("2400000");
    expect(String(body.target_book?.tax?.rate || "")).toContain("13%");
    await expect(page.getByTestId("target-book")).toBeVisible();
    await expect(page.getByTestId("target-source")).toContainText("задана вами");
    await expect(page.getByTestId("target-source")).not.toContainText("user");
    await expect(page.getByTestId("target-source")).not.toContainText("model");
    await expect(page.getByTestId("target-tax")).toContainText("2400000");
    await expect(page.getByTestId("target-tax")).toContainText("15%");
    await assertNoSeriousAxe(page, "target-book");
  });
});
