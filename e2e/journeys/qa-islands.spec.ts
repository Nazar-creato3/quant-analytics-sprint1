import { expect, test } from "@playwright/test";

const API = process.env.E2E_API_URL || "http://127.0.0.1:8100";

test.use({ video: { mode: "on", size: { width: 1440, height: 900 } } });

test("pretrade and K6 show factor rate futures goal reasons", async ({ page, request }) => {
  test.setTimeout(180_000);
  const stamp = Date.now();
  const password = `Base${stamp}aA1`;
  const email = `islands-${stamp}@example.com`;
  const reg = await request.post(`${API}/api/v1/auth/register`, {
    data: { email, password, accept_terms: true, consent_pd: true },
    timeout: 180_000,
  });
  expect(reg.status(), await reg.text()).toBe(201);
  const token = (await reg.json()).access_token as string;
  const headers = { Authorization: `Bearer ${token}` };
  const book = await request.post(`${API}/api/v1/e2e/demo-book`, { headers, data: {} });
  expect(book.status(), await book.text()).toBe(200);
  const pre = await request.post(`${API}/api/v1/portfolio/me/pretrade`, {
    headers,
    data: { trades: [], mode: "paper" },
  });
  expect(pre.ok(), await pre.text()).toBeTruthy();
  const preJson = await pre.json();
  for (const key of ["factors", "stress_rate", "futures", "goals"]) {
    expect(preJson.blocks[key].reason, key).toBeTruthy();
    expect(preJson.blocks[key].status).not.toBe("будет доступно");
  }
  const report = await request.get(`${API}/api/v1/report`, { headers });
  expect(report.ok(), await report.text()).toBeTruthy();
  const fund = (await report.json()).fund;
  for (const key of ["factors", "stress_rate", "futures", "goals"]) {
    expect(fund[key].reason, key).toBeTruthy();
  }
  const origin = process.env.E2E_BASE_URL || "http://127.0.0.1:3150";
  await page.context().addCookies([{ name: "access_token", value: token, url: origin }]);
  await page.addInitScript((liveToken) => {
    localStorage.setItem("access_token", liveToken);
    localStorage.setItem("qa.bookMode", "paper");
  }, token);
  await page.goto("/pretrade", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Пересчитать" }).click();
  await expect(page.getByTestId("d60-factors")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("d60-goals")).toContainText("нет данных");
  await page.goto("/portfolio-report", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("k6-islands")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("k6-factors")).toBeVisible();
});
