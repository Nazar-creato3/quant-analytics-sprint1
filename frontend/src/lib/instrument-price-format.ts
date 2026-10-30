/** MOEX CETS currency SECIDs and pair aliases. */
import { classifySymbol, isForexPair } from "@/lib/asset-class";
import { fmtPrice } from "@/lib/formatPrice";
const MOEX_CURRENCY_SECIDS = new Set([
  "USD000UTSTOM",
  "USD000000TOD",
  "EUR000UTSTOM",
  "EUR000000TOD",
  "CNY000000TOD",
  "CNY000UTSTOM",
  "GBP000UTSTOM",
  "HKD000UTSTOM",
  "TRY000UTSTOM",
  "KZT000UTSTOM",
  "CHF000UTSTOM",
]);

const CURRENCY_ALIASES: Record<string, string> = {
  USDRUB: "USD000UTSTOM",
  "USD/RUB": "USD000UTSTOM",
  EURRUB: "EUR000UTSTOM",
  "EUR/RUB": "EUR000UTSTOM",
  CNYRUB: "CNY000UTSTOM",
  "CNY/RUB": "CNY000UTSTOM",
};

export function isMoexCurrencySymbol(symbol: string): boolean {
  const raw = symbol.trim().toUpperCase();
  if (MOEX_CURRENCY_SECIDS.has(raw)) return true;
  if (raw in CURRENCY_ALIASES) return true;
  const compact = raw.replace(/[^A-Z0-9]/g, "");
  return compact in CURRENCY_ALIASES;
}

export function normalizeMoexCurrencySymbol(symbol: string): string {
  const raw = symbol.trim().toUpperCase();
  if (MOEX_CURRENCY_SECIDS.has(raw)) return raw;
  if (raw in CURRENCY_ALIASES) return CURRENCY_ALIASES[raw];
  const compact = raw.replace(/[^A-Z0-9]/g, "");
  if (compact in CURRENCY_ALIASES) return CURRENCY_ALIASES[compact];
  return raw;
}

export function formatInstrumentPrice(
  symbol: string,
  value: number | null | undefined,
  currency?: string | null,
): string {
  if (value == null || !Number.isFinite(value)) return "—";
  if (isMoexCurrencySymbol(symbol)) {
    return fmtPrice(value, "RUB", 4);
  }
  if (isForexPair(symbol)) {
    return fmtPrice(value, currency || classifySymbol(symbol).currency, 4);
  }
  return fmtPrice(value, currency || classifySymbol(symbol).currency);
}
