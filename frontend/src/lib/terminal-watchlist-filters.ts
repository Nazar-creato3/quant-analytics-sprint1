import type { TerminalWatchItem } from "@/types/terminal";
import type { SearchCategoryId } from "@/components/search/UniverseSearchField";
import { classifySymbol, isCryptoPair, isForexPair } from "@/lib/asset-class";

const US_TICKERS = new Set([
  "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA", "SPY", "QQQ", "DIA", "IWM",
]);
const ETF_TICKERS = new Set(["SPY", "QQQ", "DIA", "IWM", "GLD", "USO", "EWJ", "EWU", "EWG", "EWQ", "EWH", "ASHR", "EWY", "VIXY", "TLT", "UUP"]);
const MOEX_SUFFIX = /\.ME$/i;

function normalizeSector(sector?: string | null): string {
  return (sector || "").trim().toLowerCase();
}

export function resolveTerminalWatchFilterKey(item: TerminalWatchItem): SearchCategoryId {
  const sym = (item.symbol || "").trim().toUpperCase();
  const sector = normalizeSector(item.sector);
  const routed = classifySymbol(sym);

  if (isForexPair(sym) || routed.routingClass === "forex_pair" || sector.includes("fx") || sector.includes("forex") || item.feed === "forex") {
    return "fx";
  }
  if (isCryptoPair(sym) || sector.includes("crypto") || sym.endsWith("USDT")) return "crypto";
  if (sector.includes("etf") || ETF_TICKERS.has(sym)) return "etf";
  if (MOEX_SUFFIX.test(sym) || sym.endsWith(".ME") || sector.includes("moex") || routed.market === "moex") return "moex";
  if (routed.routingClass === "international" && routed.market === "europe") return "europe";
  if (routed.routingClass === "international") return "asia";
  if (sector.includes("equit") || sector.includes("stock") || sector.includes("tech")) return "equities";

  if (US_TICKERS.has(sym)) return "us";
  if (
    sym.endsWith(".L") ||
    sym.endsWith(".PA") ||
    sym.endsWith(".DE") ||
    sym.endsWith(".XETRA") ||
    sym.endsWith(".F") ||
    sym.endsWith(".AS") ||
    sym.endsWith(".SW")
  ) {
    return "europe";
  }
  if (
    sym.endsWith(".T") ||
    sym.endsWith(".HK") ||
    sym.endsWith(".SS") ||
    sym.endsWith(".SZ") ||
    sym.endsWith(".KS") ||
    sym.endsWith(".KQ") ||
    sym.endsWith(".TW")
  ) {
    return "asia";
  }

  return "all";
}

export function filterTerminalWatchRows(
  rows: TerminalWatchItem[],
  filterId: SearchCategoryId,
): TerminalWatchItem[] {
  if (filterId === "all") return rows;
  return rows.filter((row) => {
    const key = resolveTerminalWatchFilterKey(row);
    if (filterId === "us" || filterId === "europe" || filterId === "asia" || filterId === "moex") {
      return key === filterId;
    }
    return key === filterId;
  });
}
