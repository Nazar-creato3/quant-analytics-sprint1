/** Chart/API symbol normalization — forex stays EUR/USD, crypto stays BTC-USD. */
import { chartApiSymbol, classifySymbol, isForexPair } from "./asset-class";

export function normalizeChartSymbol(symbol: string): string {
  const s = (symbol || "").trim().toUpperCase();
  if (!s) return s;
  return classifySymbol(s).canonicalSymbol;
}

export function chartSymbolForApi(symbol: string): string {
  return chartApiSymbol(symbol);
}

export { chartApiSymbol, classifySymbol, isForexPair };
