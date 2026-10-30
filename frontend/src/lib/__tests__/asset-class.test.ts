import { describe, expect, it } from "vitest";
import { chartApiSymbol, classifySymbol, isCryptoPair, isForexPair } from "../asset-class";
import { inferWatchlistFilterKey } from "../watchlist-filters";
import { resolveTerminalWatchFilterKey } from "../terminal-watchlist-filters";
import { fmtPrice } from "../formatPrice";

describe("asset-class routing (chart × watchlist × search)", () => {
  it("crypto BTC/USDT is not forex and charts as BTC-USD", () => {
    const info = classifySymbol("BTC/USDT");
    expect(info.routingClass).toBe("crypto_pair");
    expect(chartApiSymbol("BTC/USDT")).toBe("BTC-USD");
    expect(isForexPair("BTC/USDT")).toBe(false);
    expect(isCryptoPair("BTC/USDT")).toBe(true);
    expect(inferWatchlistFilterKey("BTC/USDT")).toBe("crypto");
    expect(resolveTerminalWatchFilterKey({ symbol: "BTC/USDT", change_pct: null, last: 1 })).toBe(
      "crypto",
    );
  });

  it("US equity AAPL stays on the listed path", () => {
    const info = classifySymbol("AAPL");
    expect(info.routingClass).toBe("us_equity_index");
    expect(chartApiSymbol("AAPL")).toBe("AAPL");
    expect(info.currency).toBe("USD");
    expect(inferWatchlistFilterKey("AAPL")).toBe("tech");
  });

  it("IMOEX stays on the listed MOEX path", () => {
    const info = classifySymbol("IMOEX");
    expect(info.routingClass).toBe("us_equity_index");
    expect(info.market).toBe("moex");
    expect(chartApiSymbol("IMOEX")).toBe("IMOEX");
  });

  it("forex EUR/USD and USD/JPY are not rewritten as crypto", () => {
    for (const sym of ["EUR/USD", "USD/JPY"] as const) {
      const info = classifySymbol(sym);
      expect(info.routingClass).toBe("forex_pair");
      expect(chartApiSymbol(sym)).toBe(sym);
      expect(isCryptoPair(sym)).toBe(false);
      expect(inferWatchlistFilterKey(sym)).toBe("currencies");
      expect(
        resolveTerminalWatchFilterKey({ symbol: sym, change_pct: null, last: 1, feed: "forex" }),
      ).toBe("fx");
    }
  });

  it("international N225 and Samsung 005930 keep native currency", () => {
    const nikkei = classifySymbol("N225");
    expect(nikkei.routingClass).toBe("international");
    expect(chartApiSymbol("N225")).toBe("^N225");
    expect(nikkei.currency).toBe("JPY");

    const samsung = classifySymbol("005930");
    expect(samsung.routingClass).toBe("international");
    expect(samsung.canonicalSymbol).toBe("005930.KS");
    expect(chartApiSymbol("005930")).toBe("005930.KS");
    expect(samsung.currency).toBe("KRW");
    expect(fmtPrice(75000, samsung.currency)).toContain("₩");
    expect(fmtPrice(75000, samsung.currency)).not.toContain("$");
    expect(fmtPrice(189.5, "USD")).toContain("$");
  });
});
