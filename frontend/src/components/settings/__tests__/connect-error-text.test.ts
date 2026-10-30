import { describe, expect, it } from "vitest";
import { connectErrorText, syncSummaryText } from "../TradingAccountsPanel";

describe("connectErrorText", () => {
  it("shows the server detail instead of the raw status code", () => {
    const err = { message: "Request failed with status code 403", response: { data: { detail: "Боевой счёт сейчас не подключается" } } };
    expect(connectErrorText(err)).toBe("Боевой счёт сейчас не подключается");
  });

  it("falls back to a Russian message without detail", () => {
    expect(connectErrorText(new Error("Request failed with status code 500"))).toMatch(/^Не удалось подключить счёт/);
  });
});


describe("syncSummaryText", () => {
  const acc = (over: Record<string, unknown> = {}) => ({
    broker_account_id: "1",
    book_account_id: "live:tbank:1:u",
    name: "Брокерский",
    access: "read_only" as const,
    added: 12,
    duplicates: 0,
    positions: 5,
    total_rub: 150000,
    reconciled: [],
    error: null,
    ...over,
  });

  it("summarises positions, value and new operations", () => {
    const text = syncSummaryText({ venue: "tbank", mode: "live", synced_at: "", ok: true, total_rub: 150000, accounts: [acc()] });
    expect(text).toContain("5 поз.");
    expect(text).toContain("новых операций 12");
  });

  it("returns the broker error when every account failed", () => {
    const text = syncSummaryText({
      venue: "tbank", mode: "live", synced_at: "", ok: false, total_rub: 0,
      accounts: [acc({ error: "Токен недействителен или отозван" })],
    });
    expect(text).toBe("Токен недействителен или отозван");
  });
});
