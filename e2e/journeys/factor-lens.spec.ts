import { expect, test } from "@playwright/test";
import { assertNoSeriousAxe } from "./helpers/shell";

const API = process.env.E2E_API_URL || "http://127.0.0.1:8100";

test.use({ video: { mode: "on", size: { width: 1440, height: 900 } } });

test("factor lens composition and page axe", async ({ page, request }) => {
  test.setTimeout(180_000);
  const stamp = Date.now();
  const password = `Base${stamp}aA1`;
  const email = `k65-${stamp}@example.com`;
  const reg = await request.post(`${API}/api/v1/auth/register`, {
    data: { email, password, accept_terms: true, consent_pd: true },
    timeout: 120_000,
  });
  expect(reg.status(), await reg.text()).toBe(201);
  const token = (await reg.json()).access_token as string;
  const headers = { Authorization: `Bearer ${token}` };
  const book = await request.post(`${API}/api/v1/e2e/demo-book`, { headers, data: {} });
  expect(book.status(), await book.text()).toBe(200);
  const factors = await request.get(`${API}/api/v1/factors/returns`, { headers });
  expect(factors.ok()).toBeTruthy();
  const origin = process.env.E2E_BASE_URL || "http://127.0.0.1:3150";
  await page.context().addCookies([{ name: "access_token", value: token, url: origin }]);
  await page.addInitScript((liveToken) => {
    localStorage.setItem("access_token", liveToken);
    localStorage.setItem("qa.bookMode", "paper");
  }, token);
  await page.goto("/portfolio-risk", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("k65-composition")).toBeVisible({ timeout: 60_000 });
  await page.goto("/factors", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("k65-factors-page")).toBeVisible({ timeout: 60_000 });
  await assertNoSeriousAxe(page, "k65-factors");
});
