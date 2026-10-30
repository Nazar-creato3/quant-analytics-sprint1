import { expect, test } from "@playwright/test";
import { assertNoSeriousAxe } from "./helpers/shell";

const API = process.env.E2E_API_URL || "http://127.0.0.1:8100";

test.use({ video: { mode: "on", size: { width: 1440, height: 900 } } });

test("pretrade page shows 60 panel", async ({ page, request }) => {
  test.setTimeout(180_000);
  const stamp = Date.now();
  const password = `Base${stamp}aA1`;
  const email = `d60-${stamp}@example.com`;
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

  const origin = process.env.E2E_BASE_URL || "http://127.0.0.1:3100";
  await page.context().addCookies([{ name: "access_token", value: token, url: origin }]);
  await page.addInitScript(
    ({ liveToken, liveUser }) => {
      localStorage.setItem("access_token", liveToken);
      localStorage.setItem("qa.activeAccount", liveUser);
      localStorage.setItem("qa.bookMode", "paper");
    },
    { liveToken: token, liveUser: userId },
  );
  await page.goto("/pretrade", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("d60-pretrade")).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Пересчитать" }).click();
  await expect(page.locator("text=Сейчас VaR")).toBeVisible({ timeout: 60_000 });
  await assertNoSeriousAxe(page, "d60-pretrade");
});
