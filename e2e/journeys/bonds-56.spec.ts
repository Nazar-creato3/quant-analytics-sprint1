import { expect, test } from "@playwright/test";
import { assertNoSeriousAxe } from "./helpers/shell";

const API = process.env.E2E_API_URL || "http://127.0.0.1:8100";

test.use({ video: { mode: "on", size: { width: 1440, height: 900 } } });

test("demo investor bonds tab stress under 1s axe", async ({ page, request }) => {
  test.setTimeout(180_000);
  const stamp = Date.now();
  const password = `Base${stamp}aA1`;
  const email = `bonds56-${stamp}@example.com`;
  const reg = await request.post(`${API}/api/v1/auth/register`, {
    data: { email, password, accept_terms: true, consent_pd: true },
    timeout: 120_000,
  });
  expect(reg.status(), await reg.text()).toBe(201);
  const token = (await reg.json()).access_token as string;
  const part = token.split(".")[1] || "";
  const payload = JSON.parse(Buffer.from(part, "base64url").toString("utf8")) as { user_id?: string };
  const userId = String(payload.user_id || "");
  const headers = { Authorization: `Bearer ${token}` };
  const book = await request.post(`${API}/api/v1/e2e/demo-book`, { headers, data: {} });
  expect(book.status(), await book.text()).toBe(200);

  const origin = process.env.E2E_BASE_URL || `http://127.0.0.1:${process.env.E2E_PORT || "3100"}`;
  await page.context().addCookies([{ name: "access_token", value: token, url: origin }]);
  await page.addInitScript(
    ({ liveToken, liveUser }) => {
      localStorage.setItem("access_token", liveToken);
      localStorage.setItem("qa.activeAccount", liveUser);
      localStorage.setItem("qa.bookMode", "paper");
    },
    { liveToken: token, liveUser: userId },
  );

  await page.goto("/portfolio-bonds", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("bonds-panel")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("bonds-table")).toContainText("OFZ26238", { timeout: 60_000 });
  const posted = page.waitForResponse(
    (response) => response.url().includes("/bonds/stress") && response.request().method() === "GET",
    { timeout: 60_000 },
  );
  await page.getByTestId("bonds-stress-run").click();
  const stress = await posted;
  expect(stress.ok(), await stress.text()).toBeTruthy();
  const body = await stress.json();
  expect(body.elapsed_ms).toBeLessThan(1000);
  await expect(page.getByTestId("bonds-stress-result")).toBeVisible();
  await assertNoSeriousAxe(page, "bonds-56");
});
