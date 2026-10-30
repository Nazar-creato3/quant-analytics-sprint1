import { expect, test } from "@playwright/test";

// Letter а against the real stack. No request stubs.
// Not run in CI: hosted jobs stop on the billing limit.

const API = process.env.E2E_API_URL || "http://127.0.0.1:8150";

test("register login logout and refuse foreign risk notification bind data", async ({
  request,
}) => {
  const stamp = Date.now();
  const password = `Base${stamp}aA1`;
  const emailA = `base-a-${stamp}@example.com`;
  const emailB = `base-b-${stamp}@example.com`;

  const regA = await request.post(`${API}/api/v1/auth/register`, {
    data: { email: emailA, password, accept_terms: true, consent_pd: true },
  });
  expect(regA.status()).toBe(201);
  const bodyA = await regA.json();
  const tokenA = bodyA.access_token as string;
  expect(tokenA).toBeTruthy();

  const regB = await request.post(`${API}/api/v1/auth/register`, {
    data: { email: emailB, password, accept_terms: true, consent_pd: true },
  });
  expect(regB.status()).toBe(201);
  const tokenB = (await regB.json()).access_token as string;
  expect(tokenB).not.toBe(tokenA);

  const loginA = await request.post(`${API}/api/v1/auth/login`, {
    data: { email: emailA, password, accept_terms: true, consent_pd: true },
  });
  expect(loginA.ok()).toBeTruthy();

  const noToken = await request.get(`${API}/api/v1/risk/backtests`);
  expect([401, 403]).toContain(noToken.status());

  const noTokenShadow = await request.get(`${API}/api/v1/risk/shadow`);
  expect([401, 403]).toContain(noTokenShadow.status());

  const noTokenJournal = await request.get(`${API}/api/v1/qa-tools/journal`);
  expect([401, 403]).toContain(noTokenJournal.status());

  const noTokenAct = await request.get(`${API}/api/v1/act/journal`);
  expect([401, 403]).toContain(noTokenAct.status());

  const foreignBacktests = await request.get(`${API}/api/v1/risk/backtests`, {
    headers: { Authorization: `Bearer ${tokenA}` },
    params: { user_id: emailB },
  });
  expect(foreignBacktests.status()).toBe(403);

  const foreignShadow = await request.get(`${API}/api/v1/risk/shadow`, {
    headers: { Authorization: `Bearer ${tokenA}` },
    params: { user_id: emailB },
  });
  expect(foreignShadow.status()).toBe(403);

  const foreignJournal = await request.get(`${API}/api/v1/qa-tools/journal`, {
    headers: { Authorization: `Bearer ${tokenA}` },
    params: { user_id: emailB },
  });
  expect(foreignJournal.status()).toBe(403);

  const foreignAct = await request.get(`${API}/api/v1/act/journal`, {
    headers: { Authorization: `Bearer ${tokenA}` },
    params: { user_id: emailB },
  });
  expect(foreignAct.status()).toBe(403);

  const codeA = await request.get(`${API}/api/v1/notifications/telegram/code`, {
    headers: { Authorization: `Bearer ${tokenA}` },
  });
  const codeB = await request.get(`${API}/api/v1/notifications/telegram/code`, {
    headers: { Authorization: `Bearer ${tokenB}` },
  });
  expect([200, 404]).toContain(codeA.status());
  expect([200, 404]).toContain(codeB.status());
  if (codeA.ok() && codeB.ok()) {
    const jsonA = await codeA.json();
    const jsonB = await codeB.json();
    expect(jsonA.code).not.toBe(jsonB.code);
    expect(String(jsonA.code).length).toBeGreaterThanOrEqual(32);
    expect(jsonA.expires_at).toBeTruthy();

    const badBind = await request.post(`${API}/api/v1/notifications/telegram/bind`, {
      data: { code: "not-a-real-code" },
    });
    expect(badBind.status()).toBe(403);
  }

  const badUnsub = await request.post(
    `${API}/api/v1/notifications/email/unsubscribe?token=not-issued`,
  );
  expect([403, 404]).toContain(badUnsub.status());

  const logout = await request.post(`${API}/api/v1/auth/logout`, {
    headers: { Authorization: `Bearer ${tokenA}` },
  });
  expect([200, 204]).toContain(logout.status());

  const afterLogout = await request.get(`${API}/api/v1/risk/backtests`, {
    headers: { Authorization: `Bearer ${tokenA}` },
  });
  expect([401, 403]).toContain(afterLogout.status());
});
