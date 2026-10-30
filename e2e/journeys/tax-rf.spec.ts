import { expect, test } from "@playwright/test";
import { assertNoSeriousAxe } from "./helpers/shell";

const API = process.env.E2E_API_URL || "http://backend:8000";

test.use({ video: { mode: "on", size: { width: 1440, height: 900 } } });

test("tax rf flag off disclaimer methodology axe", async ({ page, request }) => {
  test.setTimeout(180_000);
  const stamp = Date.now();
  const password = `Base${stamp}aA1`;
  const email = `k3-tax-${stamp}@example.com`;
  const reg = await request.post(`${API}/api/v1/auth/register`, {
    data: { email, password, accept_terms: true, consent_pd: true },
    timeout: 120_000,
  });
  expect(reg.status(), await reg.text()).toBe(201);
  const token = (await reg.json()).access_token as string;
  const origin = process.env.E2E_BASE_URL || "http://frontend:3000";
  await page.context().addCookies([{ name: "access_token", value: token, url: origin }]);
  await page.addInitScript((liveToken) => {
    localStorage.setItem("access_token", liveToken);
    localStorage.setItem("qa.bookMode", "paper");
  }, token);

  const demo = await request.get(`${API}/api/v1/tax/demo`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(demo.status(), await demo.text()).toBe(200);
  expect((await demo.json()).status).toBe("flag_off");

  await page.goto("/tax-rf", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("tax-rf-panel")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("tax-lawyer-disclaimer")).toContainText("методика не подтверждена юристом");
  await expect(page.getByTestId("tax-flag-off")).toBeVisible();
  await expect(page.getByTestId("tax-ytd")).toContainText("нет данных");
  await assertNoSeriousAxe(page, "k3-tax-rf");

  await page.goto("/methodology/tax", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("k3-tax-method")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("tax-lawyer-disclaimer")).toContainText("методика не подтверждена юристом");
  await assertNoSeriousAxe(page, "k3-tax-methodology");
});
