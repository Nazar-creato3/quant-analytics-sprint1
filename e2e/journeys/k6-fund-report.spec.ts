import { expect, test } from "@playwright/test";
import { assertNoSeriousAxe } from "./helpers/shell";
import path from "node:path";

const API = process.env.E2E_API_URL || "http://backend:8000";

async function registerPair(request: import("@playwright/test").APIRequestContext) {
  const stamp = Date.now();
  const password = `Base${stamp}aA1`;
  const email = `k6-${stamp}@example.com`;
  const reg = await request.post(`${API}/api/v1/auth/register`, {
    data: { email, password, accept_terms: true, consent_pd: true },
    timeout: 120_000,
  });
  expect(reg.status(), await reg.text()).toBe(201);
  const body = await reg.json();
  const token = body.access_token as string;
  const part = token.split(".")[1] || "";
  const payload = JSON.parse(Buffer.from(part, "base64url").toString("utf8")) as { user_id?: string };
  return { token, userId: String(payload.user_id || "") };
}

test.use({ video: { mode: "on", size: { width: 1440, height: 900 } } });

test("demo investor fund report and public statement", async ({ page, request }) => {
  test.setTimeout(180_000);
  const { token, userId } = await registerPair(request);
  const headers = { Authorization: `Bearer ${token}` };
  const book = await request.post(`${API}/api/v1/e2e/demo-book`, { headers, data: {} });
  expect(book.status(), await book.text()).toBe(200);

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
  await page.goto("/portfolio-report", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("portfolio-report")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("k6-fund")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("k6-cagr")).toBeVisible();
  await expect(page.getByTestId("k6-max-dd")).toBeVisible();
  await expect(page.getByTestId("k6-monthly")).toBeVisible();
  await expect(page.getByTestId("k6-risk")).toBeVisible();
  await expect(page.getByTestId("k6-k1-later")).toBeVisible();
  await expect(page.getByTestId("k6-k1")).toBeVisible();
  const pdf = page.waitForEvent("download", { timeout: 60_000 });
  await page.getByTestId("k6-pdf").click();
  expect((await pdf).suggestedFilename()).toMatch(/pdf/i);
  await assertNoSeriousAxe(page, "k6-portfolio-report");

  await page.goto("/statement-review", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("k6-statement")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("k6-statement-demo")).toBeVisible();
  const fixture = path.join(__dirname, "..", "fixtures", "k6-demo-statement.xml");
  await page.getByTestId("k6-statement-file").setInputFiles(fixture);
  await expect(page.getByTestId("k6-statement-rows")).toContainText("SBER", { timeout: 60_000 });
  await expect(page.getByTestId("k6-file-deleted")).toBeVisible();
  await expect(page.getByTestId("k6-statement-pdf")).toBeVisible();
  await assertNoSeriousAxe(page, "k6-statement-review");
});
