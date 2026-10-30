import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { assertNoSeriousAxe, openLive, saveLiveProfile } from "./helpers/shell";

const API = process.env.E2E_API_URL || "http://127.0.0.1:8100";
function readTbankOps(): string {
  const candidates = [
    resolve(process.cwd(), "fixtures/tbank_operations.json"),
    resolve(process.cwd(), "../backend/app/tests/fixtures/venues/tbank_operations.json"),
  ];
  for (const p of candidates) {
    try {
      return readFileSync(p, "utf8");
    } catch {
      /* try next */
    }
  }
  throw new Error("tbank_operations.json missing (run scripts/e2e-run.sh)");
}

const OPS = JSON.parse(readTbankOps());

async function registerPair(request: import("@playwright/test").APIRequestContext) {
  const stamp = Date.now();
  const password = `Base${stamp}aA1`;
  const email = `lane1-${stamp}@example.com`;
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
  return { email, password, token, userId: String(payload.user_id || "") };
}

test("letter a isolation live API", async ({ request }) => {
  const a = await registerPair(request);
  const b = await registerPair(request);
  const login = await request.post(`${API}/api/v1/auth/login`, {
    data: { email: a.email, password: a.password },
  });
  expect(login.ok()).toBeTruthy();
  const noToken = await request.get(`${API}/api/v1/risk/backtests`);
  expect([401, 403]).toContain(noToken.status());
  for (const path of ["/api/v1/risk/shadow", "/api/v1/qa-tools/journal", "/api/v1/act/journal"]) {
    const res = await request.get(`${API}${path}`);
    expect([401, 403]).toContain(res.status());
  }
  const headers = { Authorization: `Bearer ${a.token}` };
  for (const path of [
    "/api/v1/risk/backtests",
    "/api/v1/risk/shadow",
    "/api/v1/qa-tools/journal",
    "/api/v1/act/journal",
  ]) {
    const res = await request.get(`${API}${path}`, { headers, params: { user_id: b.userId || b.email } });
    expect(res.status(), `${path} ${await res.text()}`).toBe(403);
  }
  const logout = await request.post(`${API}/api/v1/auth/logout`, { headers });
  expect([200, 204]).toContain(logout.status());
  const after = await request.get(`${API}/api/v1/risk/backtests`, { headers });
  expect([401, 403]).toContain(after.status());
});

test("letter b tbank sandbox preview", async ({ request }) => {
  const { token } = await registerPair(request);
  const res = await request.post(`${API}/api/v1/venues/tbank/preview`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { user_id: "ignored", scopes: ["read"], operations: OPS, sandbox: true },
  });
  expect(res.status(), await res.text()).toBe(200);
  const body = await res.json();
  expect(String(body.host || "")).toMatch(/^sandbox-/);
  expect(body.sandbox).toBe(true);
  expect(body.accounts[0].mode).toBe("paper");
});

test("letter v report numbers match API and screen", async ({ page, request }) => {
  test.setTimeout(180_000);
  const { token } = await registerPair(request);
  const headers = { Authorization: `Bearer ${token}` };
  const book = await request.post(`${API}/api/v1/e2e/demo-book`, { headers, data: {} });
  expect([200, 404]).toContain(book.status());
  const report = await request.get(`${API}/api/v1/report?mode=paper`, { headers });
  expect(report.status(), await report.text()).toBe(200);
  const api = await report.json();
  const twr = api?.first_screen?.twr;
  const mwr = api?.first_screen?.mwr;
  const var95 = api?.first_screen?.var_95;
  await openLive(page, "/portfolio-report");
  await expect(page.getByTestId("portfolio-report")).toBeVisible({ timeout: 60_000 });
  const screenTwr = (await page.getByTestId("report-TWR").textContent())?.trim();
  const expectedTwr = twr == null ? "нет данных" : String(twr);
  expect(screenTwr).toBe(expectedTwr);
  const screenMwr = (await page.getByTestId("report-MWR").textContent())?.trim();
  expect(screenMwr).toBe(mwr == null ? "нет данных" : String(mwr));
  if (var95 == null) {
    await expect(page.getByTestId("portfolio-report")).toContainText("нет данных");
  }
});

test("letter g profile axe no serious", async ({ page, request }) => {
  test.setTimeout(300_000);
  const { token, userId } = await registerPair(request);
  const saved = await request.post(`${API}/api/v1/investment-profile`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      user_id: userId,
      horizon: "3y",
      risk_tolerance: "moderate",
      expected_return: "0.08",
      max_position_pct: "0.20",
      max_crisis_loss_pct: "0.15",
      age: "40",
      income_12m: "100000",
      expenses_12m: "50000",
      savings: "200000",
      education: "vysshee",
      purpose: "uchet kapitala",
    },
  });
  expect(saved.status(), await saved.text()).toBe(200);
  await openLive(page, "/account");
  await expect(page.getByTestId("investment-profile")).toBeVisible({ timeout: 60_000 });
  await assertNoSeriousAxe(page, "baseline-profile");
});

test("letter d e maneuver preview edit approve journal", async ({ request }) => {
  test.setTimeout(180_000);
  const { token, userId } = await registerPair(request);
  const headers = { Authorization: `Bearer ${token}` };
  const profile = await request.post(`${API}/api/v1/investment-profile`, {
    headers,
    data: {
      user_id: userId,
      horizon: "3y",
      risk_tolerance: "moderate",
      expected_return: "0.08",
      max_position_pct: "0.20",
      max_crisis_loss_pct: "0.15",
      age: "40",
      income_12m: "100000",
      expenses_12m: "50000",
      savings: "200000",
      education: "vysshee",
      purpose: "uchet kapitala",
    },
  });
  expect(profile.status(), await profile.text()).toBe(200);
  const book = await request.post(`${API}/api/v1/e2e/demo-book`, { headers, data: {} });
  expect(book.status(), await book.text()).toBe(200);
  const preview = await request.post(`${API}/api/v1/act/preview`, {
    headers,
    data: { user_id: userId, ticker: "SBER", qty: "1", price: "250", mode: "paper" },
  });
  expect(preview.status(), await preview.text()).toBe(200);
  const impact = await preview.json();
  const before = impact?.delta?.var_95?.before;
  const after = impact?.delta?.var_95?.after;
  expect(after).not.toBe(before);
  const risk = await request.get(`${API}/api/v1/risk?mode=paper`, { headers });
  expect(risk.ok()).toBeTruthy();
  const propose = await request.post(
    `${API}/api/v1/act/propose?mode=paper&target_source=user&method=equal_weight`,
    { headers, data: {} },
  );
  expect(propose.status(), await propose.text()).toBe(200);
  const proposed = await propose.json();
  const items = (proposed.items || []) as Array<{
    maneuver_id?: string;
    id?: string;
    orders?: unknown[];
    qty?: string;
  }>;
  expect(items.length).toBeGreaterThan(0);
  const first = items[0];
  const orderCount = (first.orders || []).length;
  expect(orderCount).toBeGreaterThan(0);
  const mid = String(first.maneuver_id || first.id || "");
  expect(mid).toBeTruthy();
  const viewed = await request.post(`${API}/api/v1/act/decide`, {
    headers,
    data: { user_id: userId, maneuver_id: mid, action: "view", mode: "paper" },
  });
  expect(viewed.status(), await viewed.text()).toBe(200);
  const edited = await request.post(`${API}/api/v1/act/decide`, {
    headers,
    data: { user_id: userId, maneuver_id: mid, action: "edit", edits: { qty: "2" }, mode: "paper" },
  });
  expect(edited.status(), await edited.text()).toBe(200);
  const approved = await request.post(`${API}/api/v1/act/decide`, {
    headers,
    data: { user_id: userId, maneuver_id: mid, action: "approve", confirm: true, mode: "paper" },
  });
  expect(approved.status(), await approved.text()).toBe(200);
  const executed = await request.post(`${API}/api/v1/act/execute`, {
    headers,
    data: { user_id: userId, maneuver_id: mid, mode: "paper" },
  });
  expect([200, 400, 403]).toContain(executed.status());
  const journal = await request.get(`${API}/api/v1/act/journal`, { headers });
  expect(journal.ok()).toBeTruthy();
  const journalBody = await journal.json();
  expect(JSON.stringify(journalBody)).toContain(mid);
  const noPrice = await request.post(`${API}/api/v1/act/preview`, {
    headers,
    data: { user_id: userId, ticker: "SBER", qty: "1", price: "", mode: "paper" },
  });
  expect([400, 422]).toContain(noPrice.status());
  const noPriceText = await noPrice.text();
  expect(noPriceText).toContain("нет данных");
});

test("letter zh refuse missing price on order machine", async ({ request }) => {
  const { token } = await registerPair(request);
  const res = await request.post(`${API}/api/v1/orders/machine`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      client_order_id: `lane1-${Date.now()}`,
      ticker: "SBER",
      side: "buy",
      qty: "1",
      ccy: "RUB",
      price: null,
      mode: "paper",
      confirmed: true,
    },
  });
  expect([200, 400, 422]).toContain(res.status());
  const raw = await res.text();
  let body: unknown = { detail: raw };
  try {
    body = JSON.parse(raw);
  } catch {
    /* keep text */
  }
  const blob = JSON.stringify(body);
  expect(blob.includes("rejected") || blob.includes("нет данных") || blob.includes("off")).toBeTruthy();
});

test("letter z empty report and envelope without fetch", async ({ page, request }) => {
  test.setTimeout(180_000);
  const { token } = await registerPair(request);
  const env = await request.get(`${API}/api/v1/market/quote-envelope?symbol=SBER`);
  expect(env.ok()).toBeTruthy();
  const envBody = await env.json();
  expect(envBody.price === null || envBody.price === undefined || envBody.price === "" || envBody.price === "нет данных").toBeTruthy();
  const report = await request.get(`${API}/api/v1/report?mode=paper`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(report.ok()).toBeTruthy();
  const api = await report.json();
  if (api.empty || api.first_screen?.data_status === "нет данных" || api.first_screen?.twr == null) {
    await openLive(page, "/portfolio-report");
    await expect(page.getByTestId("report-TWR")).toHaveText("нет данных", { timeout: 60_000 });
  }
});
