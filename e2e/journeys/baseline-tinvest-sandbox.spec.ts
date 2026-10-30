import { test, expect } from "@playwright/test";

/**
 * Baseline letter б — T-Invest sandbox preview without founder live keys.
 * Uses fixture-shaped operations; host must be sandbox-invest-public-api.
 */
test("tbank sandbox preview uses sandbox host and paper account", async ({ request }) => {
  const ops = [
    {
      external_id: `e2e-sb-${Date.now()}`,
      kind: "buy",
      ticker: "SBER",
      qty: "10",
      amount: "2500",
      ccy: "RUB",
      event_time: "2024-01-15T10:00:00+00:00",
    },
  ];
  const API = process.env.E2E_API_URL || "http://127.0.0.1:8150";
  const res = await request.post(`${API}/api/v1/venues/tbank/preview`, {
    data: {
      user_id: `e2e-letter-b-${Date.now()}`,
      scopes: ["read"],
      operations: ops,
      sandbox: true,
      readonly: true,
    },
  });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(String(body.host || "")).toContain("sandbox-");
  expect(body.sandbox).toBeTruthy();
  expect(body.accounts?.[0]?.mode).toBe("paper");
  expect(body.trade_enabled).toBeFalsy();
});
