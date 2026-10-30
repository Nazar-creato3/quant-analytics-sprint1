import { expect, test } from "@playwright/test";
import { assertNoSeriousAxe } from "./helpers/shell";

const API = process.env.E2E_API_URL || "http://127.0.0.1:8100";

test.use({ video: { mode: "on", size: { width: 1440, height: 900 } } });

test("k3 tax demo investor axe", async ({ page, request }) => {
  test.setTimeout(240_000);
  const stamp = Date.now();
  const password = `Base${stamp}aA1`;
  const email = `k3-${stamp}@example.com`;
  const reg = await request.post(`${API}/api/v1/auth/register`, {
    data: { email, password, accept_terms: true, consent_pd: true },
    timeout: 180_000,
  });
  expect(reg.status(), await reg.text()).toBe(201);
  const token = (await reg.json()).access_token as string;
  const headers = { Authorization: `Bearer ${token}` };
  const book = await request.post(`${API}/api/v1/e2e/demo-book`, { headers, data: {} });
  expect(book.status(), await book.text()).toBe(200);
  const tax = await request.get(`${API}/api/v1/tax?mode=paper&resident=true`, { headers });
  expect(tax.ok(), await tax.text()).toBeTruthy();
  const body = await tax.json();
  expect(body.lawyer_gate).toContain("ЮРИСТ");
  expect(body.demo_only).toBeTruthy();
  const origin = process.env.E2E_BASE_URL || "http://127.0.0.1:3150";
  await page.context().addCookies([{ name: "access_token", value: token, url: origin }]);
  await page.addInitScript((liveToken) => {
    localStorage.setItem("access_token", liveToken);
    localStorage.setItem("qa.bookMode", "paper");
  }, token);
  await page.goto("/tax", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("k3-tax")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("k3-status")).toBeVisible();
  await expect(page.getByTestId("k3-method")).toBeVisible();
  await assertNoSeriousAxe(page, "k3-tax");
});
