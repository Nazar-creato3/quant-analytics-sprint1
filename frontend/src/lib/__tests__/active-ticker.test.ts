import { describe, expect, it } from "vitest";
import { DEFAULT_ACTIVE_TICKER, normalizeActiveTicker } from "@/lib/active-ticker";

describe("normalizeActiveTicker", () => {
  it("uppercases and trims", () => {
    expect(normalizeActiveTicker("  aapl ")).toBe("AAPL");
  });

  it("falls back when empty", () => {
    expect(normalizeActiveTicker("")).toBe(DEFAULT_ACTIVE_TICKER);
    expect(normalizeActiveTicker(null)).toBe(DEFAULT_ACTIVE_TICKER);
  });

  it("maps class shares to dotted ticker", () => {
    expect(normalizeActiveTicker("brk b")).toBe("BRK.B");
    expect(normalizeActiveTicker("BRK.B")).toBe("BRK.B");
  });

  it("strips accidental interior spaces on ordinary tickers", () => {
    expect(normalizeActiveTicker("aa pl")).toBe("AAPL");
  });
});
