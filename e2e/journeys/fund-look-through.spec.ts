import { expect, test } from "@playwright/test";
import { assertNoSeriousAxe } from "./helpers/shell";

const API = process.env.E2E_API_URL || "http://backend:8000";

test.use({ video: { mode: "on", size: { width: 1440, height: 900 } } });

test("look-through structure methodology and axe", async ({ page, request }) => {
  test.setTimeout(180_000);
  const stamp = Date.now();
  const password = `Base${stamp}aA1`;
  const email = `k61-${stamp}@example.com`;
  const reg = await request.post(`${API}/api/v1/auth/register`, {
    data: { email, password, accept_terms: true, consent_pd: true },
    timeout: 120_000,
  });
  expect(reg.status(), await reg.text()).toBe(201);
  const body = await reg.json();
  const token = body.access_token as string;
  const part = token.split(".")[1] || "";
  const payload = JSON.parse(Buffer.from(part, "base64url").toString("utf8")) as { user_id?: string };
  const userId = String(payload.user_id || "");
  const headers = { Authorization: `Bearer ${token}` };
  const book = await request.post(`${API}/api/v1/e2e/demo-book`, { headers, data: {} });
  expect(book.status(), await book.text()).toBe(200);

  const look = await request.get(`${API}/api/v1/portfolio/me/lookthrough`, {
    headers,
    params: { by: "issuer" },
  });
  expect(look.status(), await look.text()).toBe(200);
  const holdings = await request.get(`${API}/api/v1/funds/TMOS/holdings`, { headers });
  expect(holdings.status(), await holdings.text()).toBe(200);

  const origin = process.env.E2E_BASE_URL || "http://frontend:3000";
  await page.context().addCookies([{ name: "access_token", value: token, url: origin }]);
  await page.addInitScript(
    ({ liveToken, liveUser }) => {
      localStorage.setItem("access_token", liveToken);
      localStorage.setItem("qa.activeAccount", liveUser);
      localStorage.setItem("qa.bookMode", "paper");
    },
    { liveToken: token, liveUser: userId },
  );

  await page.goto("/portfolio-structure", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("k61-lookthrough")).toBeVisible({ timeout: 60_000 });
  const brokerToggle = page.getByTestId("k61-view-broker");
  if (await brokerToggle.count()) {
    await brokerToggle.click();
    await page.getByTestId("k61-view-lookthrough").click();
  }
  await assertNoSeriousAxe(page, "k61-portfolio-structure");

  await page.goto("/methodology/fund-look-through", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("k61-method")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("k61-method")).toContainText(/глубины 3|состав не раскрыт/);
  await assertNoSeriousAxe(page, "k61-methodology");
});
