import type { WatchlistEntry } from "@/lib/api";
import { isForexPair, isCryptoPair } from "@/lib/asset-class";
import { isMoexCurrencySymbol } from "@/lib/instrument-price-format";

export type DirectDealsWatchGroup = "indices" | "stocks" | "currencies" | "crypto";

export const DIRECT_DEALS_WATCH_GROUPS: { id: DirectDealsWatchGroup; label: string }[] = [
  { id: "indices", label: "Индексы" },
  { id: "stocks", label: "Акции" },
  { id: "currencies", label: "Валюты" },
  { id: "crypto", label: "Crypto" },
];

const INDEX_SYMBOLS = new Set([
  "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "GLD", "USO", "TLT", "HYG",
  "EEM", "EFA", "XLF", "XLK", "XLE", "SPX", "NDX", "RUT", "IMOEX",
]);

function isCryptoSymbol(sym: string): boolean {
  if (isMoexCurrencySymbol(sym) || isForexPair(sym)) return false;
  return isCryptoPair(sym);
}

/** Classify watchlist symbol into Indices / Stocks / Crypto buckets. */
export function resolveDirectDealsWatchGroup(
  symbol: string,
  entry?: WatchlistEntry,
): DirectDealsWatchGroup {
  const sym = symbol.toUpperCase();
  if (entry?.category === "fx" || entry?.filter_key === "currencies" || isMoexCurrencySymbol(sym) || isForexPair(sym)) {
    return "currencies";
  }
  if (entry?.category === "crypto" || isCryptoSymbol(sym)) return "crypto";
  if (entry?.category === "etf" || entry?.filter_key === "etf" || INDEX_SYMBOLS.has(sym)) {
    return "indices";
  }
  return "stocks";
}

export function groupWatchlistTickers(
  tickers: string[],
  entries: WatchlistEntry[],
): Record<DirectDealsWatchGroup, string[]> {
  const bySymbol = new Map(entries.map((e) => [e.symbol.toUpperCase(), e]));
  const groups: Record<DirectDealsWatchGroup, string[]> = {
    indices: [],
    stocks: [],
    currencies: [],
    crypto: [],
  };
  for (const t of tickers) {
    const sym = t.toUpperCase();
    groups[resolveDirectDealsWatchGroup(sym, bySymbol.get(sym))].push(sym);
  }
  return groups;
}
