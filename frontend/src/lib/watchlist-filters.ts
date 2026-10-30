import { isMoexSymbol } from "./moex-symbols";
import type { WatchlistEntry } from "@/lib/api";
import { classifySymbol, isCryptoPair, isForexPair } from "@/lib/asset-class";

export type WatchlistFilterId = "all" | "russia" | "tech" | "etf" | "crypto" | "currencies" | "other";

export const WATCHLIST_FILTERS: { id: WatchlistFilterId; label: string }[] = [
  { id: "all", label: "Все" },
  { id: "russia", label: "Россия" },
  { id: "tech", label: "Технологии" },
  { id: "etf", label: "ETF" },
  { id: "crypto", label: "Крипто" },
  { id: "currencies", label: "Валюты" },
  { id: "other", label: "Другое" },
];

/** Resolve filter tab from backend entry; mirrors watchlist_filter_key on the server. */
export function resolveWatchlistFilterKey(entry: WatchlistEntry): WatchlistFilterId {
  if (entry.filter_key) {
    return entry.filter_key as WatchlistFilterId;
  }
  if (entry.category === "crypto") return "crypto";
  if (entry.category === "fx" || entry.filter_key === "currencies") return "currencies";
  if (entry.category === "etf") return "etf";
  if (
    entry.category === "equities" &&
    entry.sector &&
    ["technology", "communication_services", "consumer_discretionary"].includes(entry.sector)
  ) {
    return "tech";
  }
  return "other";
}

export function filterWatchlistEntries(
  entries: WatchlistEntry[],
  filterId: WatchlistFilterId,
): WatchlistEntry[] {
  if (filterId === "all") return entries;
  return entries.filter(entry => resolveWatchlistFilterKey(entry) === filterId);
}

export function filterWatchlistTickers(
  tickers: string[],
  entries: WatchlistEntry[] | undefined,
  filterId: WatchlistFilterId,
): string[] {
  if (filterId === "all") return tickers;
  if (filterId === "russia") {
    // A market filter, not a category: Moscow Exchange shares, funds and indices.
    const moex = new Set(
      (entries ?? []).filter(e => String(e.market || "").startsWith("moex")).map(e => e.symbol),
    );
    return tickers.filter(ticker => moex.has(ticker) || isMoexSymbol(ticker));
  }
  if (entries?.length) {
    const allowed = new Set(
      filterWatchlistEntries(entries, filterId).map(entry => entry.symbol),
    );
    return tickers.filter(ticker => allowed.has(ticker));
  }
  return tickers.filter(ticker => inferWatchlistFilterKey(ticker) === filterId);
}

const ETF_SYMBOLS = new Set(["SPY", "QQQ", "DIA", "IWM", "GLD", "USO", "VTI", "VOO"]);

/** Heuristic when backend watchlist metadata is missing. */
export function inferWatchlistFilterKey(symbol: string): WatchlistFilterId {
  const s = symbol.trim().toUpperCase();
  if (isForexPair(s) || classifySymbol(s).routingClass === "forex_pair") return "currencies";
  if (isCryptoPair(s)) return "crypto";
  if (ETF_SYMBOLS.has(s)) return "etf";
  if (isMoexSymbol(s)) return "other";
  if (["AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA"].includes(s)) {
    return "tech";
  }
  return "other";
}
