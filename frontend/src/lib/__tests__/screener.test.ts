import { describe, expect, it } from "vitest";
import {
  DEFAULT_SCREENER_DRAFT,
  draftToScreenerParams,
  sortScreenerRows,
  terminalHrefForTicker,
} from "@/lib/screener";

describe("draftToScreenerParams", () => {
  it("maps default US mega-ish draft", () => {
    const params = draftToScreenerParams(DEFAULT_SCREENER_DRAFT);
    expect(params.country).toBe("US");
    expect(params.marketCapMoreThan).toBe(10_000_000_000);
    expect(params.isActivelyTrading).toBe(true);
    expect(params.limit).toBe(50);
  });

  it("omits empty numeric filters", () => {
    const params = draftToScreenerParams({
      ...DEFAULT_SCREENER_DRAFT,
      mcapMin: "",
      peMax: "18",
      dividendMin: "2.5",
    });
    expect(params.marketCapMoreThan).toBeUndefined();
    expect(params.peLowerThan).toBe(18);
    expect(params.dividendMoreThan).toBe(2.5);
  });
});

describe("sortScreenerRows", () => {
  it("sorts nulls last", () => {
    const rows = sortScreenerRows(
      [
        { symbol: "A", market_cap: null },
        { symbol: "B", market_cap: 3e12 },
        { symbol: "C", market_cap: 1e9 },
      ],
      "market_cap",
      "desc",
    );
    expect(rows.map((r) => r.symbol)).toEqual(["B", "C", "A"]);
  });
});

describe("terminalHrefForTicker", () => {
  it("staff lands on Terminal with symbol", () => {
    expect(terminalHrefForTicker("nvda", true)).toBe("/terminal?symbol=NVDA");
  });

  it("non-staff lands on Forecast desk", () => {
    expect(terminalHrefForTicker("nvda", false)).toBe("/forecasting?symbol=NVDA");
  });
});
