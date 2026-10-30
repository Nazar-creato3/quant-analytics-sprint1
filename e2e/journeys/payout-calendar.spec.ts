import { expect, test } from "@playwright/test";
import { assertNoSeriousAxe } from "./helpers/shell";

const API = process.env.E2E_API_URL || "http://127.0.0.1:8100";

test.use({ video: { mode: "on", size: { width: 1440, height: 900 } } });

test("demo calendar months filters axe", async ({ page, request }) => {
  test.setTimeout(180_000);
  const stamp = Date.now();
  const password = `Base${stamp}aA1`;
  const email = `payouts57-${stamp}@example.com`;
  const reg = await request.post(`${API}/api/v1/auth/register`, {
    data: { email, password, accept_terms: true, consent_pd: true },
    timeout: 120_000,
  });
  expect(reg.status(), await reg.text()).toBe(201);
  const token = (await reg.json()).access_token as string;
  await request.post(`${API}/api/v1/e2e/demo-book`, { headers: { Authorization: `Bearer ${token}` } });
  const origin = process.env.E2E_BASE_URL || "http://127.0.0.1:3150";
  await page.context().addCookies([{ name: "access_token", value: token, url: origin }]);
  await page.addInitScript((liveToken) => {
    localStorage.setItem("access_token", liveToken);
    localStorage.setItem("qa.bookMode", "paper");
  }, token);
  await page.goto("/payout-calendar", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("payout-calendar")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("payout-list")).toContainText("SBER", { timeout: 60_000 });
  await page.getByTestId("payout-month").fill("2026-12");
  await page.getByTestId("payout-filter").selectOption("dividend");
  await assertNoSeriousAxe(page, "payouts-57");
});
