import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const API = process.env.E2E_API_URL || "http://127.0.0.1:8100";

test.use({ video: { mode: "on", size: { width: 1440, height: 900 } } });

test("brain now shows a signal list", async ({ page, request }) => {
  test.setTimeout(240_000);
  const stamp = Date.now();
  const password = `Base${stamp}aA1`;
  const email = `brain-${stamp}@example.com`;
  const reg = await request.post(`${API}/api/v1/auth/register`, {
    data: { email, password, accept_terms: true, consent_pd: true },
    timeout: 180_000,
  });
  expect(reg.status(), await reg.text()).toBe(201);
  const token = (await reg.json()).access_token as string;
  const origin = process.env.E2E_BASE_URL || "http://127.0.0.1:3150";
  await page.context().addCookies([{ name: "access_token", value: token, url: origin }]);
  await page.addInitScript((liveToken) => {
    localStorage.setItem("access_token", liveToken);
  }, token);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("brain-now")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("brain-caption")).toBeVisible();
  const signals = page.locator("[data-testid^='brain-signal-']");
  await expect(signals.first()).toBeVisible({ timeout: 90_000 });
  const count = await signals.count();
  expect(count).toBeGreaterThan(0);
  expect(count).toBeLessThanOrEqual(5);
  const results = await new AxeBuilder({ page })
    .include("[data-testid=brain-now]")
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  const blocking = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(blocking.map((v) => v.id)).toEqual([]);
});
