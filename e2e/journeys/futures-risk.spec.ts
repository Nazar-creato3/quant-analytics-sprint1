import { expect, test } from "@playwright/test";
import { assertNoSeriousAxe } from "./helpers/shell";

const API = process.env.E2E_API_URL || "http://127.0.0.1:8100";

test.use({ video: { mode: "on", size: { width: 1440, height: 900 } } });

test("futures risk hedge axe", async ({ page, request }) => {
  test.setTimeout(240_000);
  const stamp = Date.now();
  const password = `Base${stamp}aA1`;
  const email = `k58a-${stamp}@example.com`;
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
  await page.goto("/futures-risk", { waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(/\/futures$/);
  await expect(page.getByTestId("fut-mine")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("k58a-panel")).toBeVisible({ timeout: 60_000 });
  await assertNoSeriousAxe(page, "k58a-futures");
});
