import { expect, test } from "@playwright/test";
import { assertNoSeriousAxe } from "./helpers/shell";

const API = process.env.E2E_API_URL || "http://127.0.0.1:8100";

async function registerPair(request: import("@playwright/test").APIRequestContext) {
  const stamp = Date.now();
  const password = `Base${stamp}aA1`;
  const email = `k4-${stamp}@example.com`;
  const reg = await request.post(`${API}/api/v1/auth/register`, {
    data: { email, password, accept_terms: true, consent_pd: true },
    timeout: 120_000,
  });
  expect(reg.status(), await reg.text()).toBe(201);
  const body = await reg.json();
  const token = body.access_token as string;
  expect(token).toBeTruthy();
  const part = token.split(".")[1] || "";
  const payload = JSON.parse(Buffer.from(part, "base64url").toString("utf8")) as { user_id?: string };
  return { token, userId: String(payload.user_id || "") };
}

test.use({ video: { mode: "on", size: { width: 1440, height: 900 } } });

test("demo investor table what-if axe", async ({ page, request }) => {
    test.setTimeout(180_000);
    const { token, userId } = await registerPair(request);
    const headers = { Authorization: `Bearer ${token}` };
    const book = await request.post(`${API}/api/v1/e2e/demo-book`, { headers, data: {} });
    expect(book.status(), await book.text()).toBe(200);
    const beforeRisk = await request.get(`${API}/api/v1/risk?mode=paper`, { headers });
    expect(beforeRisk.ok()).toBeTruthy();
    const riskJson = await beforeRisk.json();
    const rows = riskJson?.attribution?.components ?? [];
    expect(rows.length).toBeGreaterThan(0);
    const largest = String(rows[0].ticker);
    const beforeBook = await request.get(`${API}/api/v1/book/positions?mode=paper`, { headers });
    expect(beforeBook.ok()).toBeTruthy();
    const bookBefore = await beforeBook.json();

    const origin = process.env.E2E_BASE_URL || "http://127.0.0.1:3150";
    await page.context().addCookies([{ name: "access_token", value: token, url: origin }]);
    await page.addInitScript(
      ({ liveToken, liveUser }) => {
        localStorage.setItem("access_token", liveToken);
        localStorage.setItem("qa.activeAccount", liveUser);
        localStorage.setItem("qa.bookMode", "paper");
      },
      { liveToken: token, liveUser: userId },
    );
    await page.goto("/portfolio?tab=risk", { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("k4-attribution")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("k4-table")).toContainText(largest, { timeout: 60_000 });
    await expect(page.getByTestId("k4-enb")).toBeVisible();
    const volBefore = (await page.getByTestId(`k4-vol-${largest}`).textContent())?.trim();
    await page.getByTestId(`k4-drop-${largest}`).click();
    const posted = page.waitForResponse(
      (response) => response.url().includes("/risk/what-if") && response.request().method() === "POST",
      { timeout: 60_000 },
    );
    await page.getByTestId("k4-recalc").click();
    const whatIf = await posted;
    expect(whatIf.ok(), await whatIf.text()).toBeTruthy();
    await expect(page.getByTestId("k4-not-saved")).toBeVisible({ timeout: 30_000 });
    const previewRows = ((await whatIf.json())?.attribution?.components ?? []) as Array<{ ticker: string }>;
    expect(previewRows.map((r) => r.ticker)).not.toContain(largest);
    expect(volBefore).toBeTruthy();

    const afterBook = await request.get(`${API}/api/v1/book/positions?mode=paper`, { headers });
    expect(await afterBook.json()).toEqual(bookBefore);
    const afterRisk = await request.get(`${API}/api/v1/risk?mode=paper`, { headers });
    const afterRows = (await afterRisk.json())?.attribution?.components ?? [];
    expect(afterRows.map((r: { ticker: string }) => r.ticker).sort()).toEqual(
      rows.map((r: { ticker: string }) => r.ticker).sort(),
    );
    await assertNoSeriousAxe(page, "k4-portfolio-risk");
  });
