import { describe, it, expect } from "vitest";
import { chartSymbolForApi, normalizeChartSymbol } from "../chartSymbol";

describe("chartSymbol", () => {
  it("uppercases", () => {
    expect(normalizeChartSymbol("spy")).toBe("SPY");
  });

  it("does not rewrite forex as crypto", () => {
    expect(normalizeChartSymbol("eur/usd")).toBe("EUR/USD");
    expect(chartSymbolForApi("EUR/USD")).toBe("EUR/USD");
    expect(chartSymbolForApi("USDJPY")).toBe("USD/JPY");
  });

  it("maps crypto slash pairs to BASE-USD", () => {
    expect(chartSymbolForApi("BTC/USDT")).toBe("BTC-USD");
  });

  it("maps Samsung and Nikkei to international API symbols", () => {
    expect(chartSymbolForApi("005930")).toBe("005930.KS");
    expect(chartSymbolForApi("N225")).toBe("^N225");
  });
});
