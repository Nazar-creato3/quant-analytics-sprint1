import { describe, expect, it } from "vitest";
import { filterWatchlistTickers, WATCHLIST_FILTERS } from "../watchlist-filters";
import type { WatchlistEntry } from "@/lib/api";

const entry = (symbol: string, market: string): WatchlistEntry => ({
  symbol, market, category: "equities", sector: null, label: symbol, label_ru: symbol,
});

describe("Россия filter", () => {
  it("comes right after Все", () => {
    expect(WATCHLIST_FILTERS.slice(0, 2).map(f => f.label)).toEqual(["Все", "Россия"]);
  });

  it("keeps Moscow Exchange tickers only", () => {
    const tickers = ["SBER", "AAPL", "IMOEX", "XLK", "YDEX"];
    const entries = [entry("SBER", "moex"), entry("AAPL", "us"), entry("IMOEX", "moex_index"), entry("XLK", "us"), entry("YDEX", "moex")];
    expect(filterWatchlistTickers(tickers, entries, "russia")).toEqual(["SBER", "IMOEX", "YDEX"]);
  });

  it("works without server metadata", () => {
    expect(filterWatchlistTickers(["GAZP", "NVDA"], undefined, "russia")).toEqual(["GAZP"]);
  });
});
