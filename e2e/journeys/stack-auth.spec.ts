import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const API = process.env.E2E_API_URL || "http://127.0.0.1:8150";

test("stand stack register, login, and isolation without request stubs", async ({
  page,
  request,
}, testInfo) => {
  const stamp = Date.now();
  const password = `Stand${stamp}aA1`;
  const emailA = `stand-a-${stamp}@example.com`;
  const emailB = `stand-b-${stamp}@example.com`;

  const health = await request.get(`${API}/api/v1/health`);
  expect(health.ok()).toBeTruthy();

  const regA = await request.post(`${API}/api/v1/auth/register`, {
    data: { email: emailA, password, accept_terms: true, consent_pd: true },
  });
  expect(regA.status()).toBe(201);
  const tokenA = (await regA.json()).access_token as string;
  expect(tokenA.length).toBeGreaterThan(10);

  const loginA = await request.post(`${API}/api/v1/auth/login`, {
    data: { email: emailA, password, accept_terms: true, consent_pd: true },
  });
  expect(loginA.ok()).toBeTruthy();

  const meA = await request.get(`${API}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${tokenA}` },
  });
  expect(meA.ok()).toBeTruthy();
  const bodyA = await meA.json();
  expect(bodyA.email).toBe(emailA);

  const regB = await request.post(`${API}/api/v1/auth/register`, {
    data: { email: emailB, password, accept_terms: true, consent_pd: true },
  });
  expect(regB.status()).toBe(201);
  const tokenB = (await regB.json()).access_token as string;

  const meB = await request.get(`${API}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${tokenB}` },
  });
  expect(meB.ok()).toBeTruthy();
  const bodyB = await meB.json();
  expect(bodyB.email).toBe(emailB);
  expect(bodyB.id).not.toBe(bodyA.id);

  const foreign = await request.get(`${API}/api/v1/auth/me`, {
    headers: { Authorization: "Bearer not-a-token" },
  });
  expect([401, 403]).toContain(foreign.status());

  await page.goto("/login");
  await expect(page.getByText(/Quant Analytics|Вход/i).first()).toBeVisible();
  await expect(page.locator('input[type="email"], input[name="email"]').first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("stack-login.png"), fullPage: true });

  const axe = await new AxeBuilder({ page }).analyze();
  const blocking = axe.violations.filter(
    (item) => item.impact === "serious" || item.impact === "critical",
  );
  expect(blocking, JSON.stringify(blocking)).toEqual([]);
});
