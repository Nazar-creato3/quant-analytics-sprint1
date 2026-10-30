import { describe, expect, it } from "vitest";
import { BROKER_SYNC_STALE_MS, hasTinkoffKey, syncIsStale } from "../useBrokerAutoSync";

describe("syncIsStale", () => {
  const now = Date.parse("2026-10-27T12:00:00Z");
  it("is stale when nothing was synced", () => expect(syncIsStale([], now)).toBe(true));
  it("is fresh right after a sync", () => expect(syncIsStale(["2026-10-27T11:55:00Z"], now)).toBe(false));
  it("is stale after the window", () =>
    expect(syncIsStale([new Date(now - BROKER_SYNC_STALE_MS - 1000).toISOString()], now)).toBe(true));
});

describe("hasTinkoffKey", () => {
  const overview = {
    venues: [{ venue: "tinkoff", connected_accounts: [{ connected: true, account_mode: "live" }] }],
  } as never;
  it("matches the mode", () => {
    expect(hasTinkoffKey(overview, "live")).toBe(true);
    expect(hasTinkoffKey(overview, "paper")).toBe(false);
  });
});
