import { isMoexSymbol } from "./moex-symbols";
/** Four routing classes shared by Terminal chart, Watchlist, and search. */

export type RoutingClass =
  | "crypto_pair"
  | "us_equity_index"
  | "forex_pair"
  | "international"
  | "other";

export interface AssetClassInfo {
  routingClass: RoutingClass;
  canonicalSymbol: string;
  chartApiSymbol: string;
  currency: string;
  showVolume: boolean;
  market: string;
}

const ISO4217 = new Set([
  "USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD", "NOK", "SEK", "DKK",
  "SGD", "HKD", "CNY", "MXN", "ZAR", "TRY", "PLN", "HUF", "CZK", "INR", "KRW",
  "BRL", "RUB",
]);

const CRYPTO_BASES = new Set([
  "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "DOT", "LINK",
]);

const US_INDEX_UI = new Set([
  "SPX", "IXIC", "NDX", "DJI", "RUT", "VIX", "DXY", "US10Y", "GOLD", "OIL",
]);

const INTL_INDEX_UI: Record<string, { api: string; currency: string }> = {
  N225: { api: "^N225", currency: "JPY" },
  HSI: { api: "^HSI", currency: "HKD" },
  KS11: { api: "^KS11", currency: "KRW" },
  SSEC: { api: "000001.SS", currency: "CNY" },
  FTSE: { api: "^FTSE", currency: "GBP" },
  DAX: { api: "^GDAXI", currency: "EUR" },
  FCHI: { api: "^FCHI", currency: "EUR" },
  CAC: { api: "^FCHI", currency: "EUR" },
};

const SUFFIX_CURRENCY: Record<string, string> = {
  ".T": "JPY",
  ".HK": "HKD",
  ".KS": "KRW",
  ".KQ": "KRW",
  ".TW": "TWD",
  ".SS": "CNY",
  ".SZ": "CNY",
  ".XETRA": "EUR",
  ".DE": "EUR",
  ".F": "EUR",
  ".PA": "EUR",
  ".AS": "EUR",
  ".L": "GBP",
  ".SW": "CHF",
  ".ME": "RUB",
};

const INTL_ALIASES: Record<string, string> = {
  "005930": "005930.KS",
  "000660": "000660.KS",
  "2330": "2330.TW",
  "0700": "0700.HK",
  "700": "0700.HK",
};

const INTL_SUFFIXES = Object.keys(SUFFIX_CURRENCY).filter((s) => s !== ".ME");

function compact(symbol: string): string {
  return symbol.replace(/[\s/\-_]/g, "");
}

function suffixCurrency(sym: string): string | undefined {
  for (const [sfx, code] of Object.entries(SUFFIX_CURRENCY)) {
    if (sym.endsWith(sfx)) return code;
  }
  return undefined;
}

export function isForexPair(symbol: string): boolean {
  const raw = symbol.trim().toUpperCase();
  if (!raw || raw.endsWith("USDT") || raw.includes("000")) return false;
  const c = compact(raw);
  if (c.length === 6 && ISO4217.has(c.slice(0, 3)) && ISO4217.has(c.slice(3)) && c.slice(0, 3) !== c.slice(3)) {
    if (CRYPTO_BASES.has(c.slice(0, 3))) return false;
    return true;
  }
  if (raw.length === 7 && "/-_".includes(raw[3])) {
    const base = raw.slice(0, 3);
    const quote = raw.slice(4);
    return ISO4217.has(base) && ISO4217.has(quote) && base !== quote && !CRYPTO_BASES.has(base);
  }
  return false;
}

export function canonicalForexSymbol(symbol: string): string | null {
  if (!isForexPair(symbol)) return null;
  const raw = symbol.trim().toUpperCase();
  const c = compact(raw);
  if (c.length === 6) return `${c.slice(0, 3)}/${c.slice(3)}`;
  return raw.replace(/[-_]/g, "/");
}

export function isCryptoPair(symbol: string): boolean {
  if (isForexPair(symbol)) return false;
  const raw = symbol.trim().toUpperCase().replace("/", "-");
  if (raw.endsWith("USDT")) {
    const base = raw.replace(/-?USDT$/, "");
    return /^[A-Z]{2,10}$/.test(base);
  }
  if (raw.endsWith("-USD")) {
    const base = raw.slice(0, -4);
    return CRYPTO_BASES.has(base) || /^[A-Z]{2,10}$/.test(base);
  }
  return CRYPTO_BASES.has(raw.split("-")[0]);
}

function canonicalizeInternational(symbol: string): string | null {
  const raw = symbol.trim().toUpperCase();
  if (INTL_ALIASES[raw]) return INTL_ALIASES[raw];
  if (INTL_SUFFIXES.some((sfx) => raw.endsWith(sfx))) return raw;
  if (/^\d{6}$/.test(raw)) return `${raw}.KS`;
  if (/^0\d{3}$/.test(raw)) return `${raw}.HK`;
  return null;
}

export function classifySymbol(symbol: string): AssetClassInfo {
  const raw = (symbol || "").trim().toUpperCase();
  const fx = canonicalForexSymbol(raw);
  if (fx) {
    return {
      routingClass: "forex_pair",
      canonicalSymbol: fx,
      chartApiSymbol: fx,
      currency: fx.split("/")[1] || "USD",
      showVolume: false,
      market: "forex",
    };
  }
  if (isCryptoPair(raw)) {
    const dashed = raw.replace("/", "-");
    const usdtBase = dashed.endsWith("USDT") ? dashed.replace(/-?USDT$/, "") : "";
    const canon = usdtBase
      ? `${usdtBase}-USD`
      : dashed.endsWith("-USD")
        ? dashed
        : CRYPTO_BASES.has(dashed)
          ? `${dashed}-USD`
          : dashed;
    return {
      routingClass: "crypto_pair",
      canonicalSymbol: canon,
      chartApiSymbol: canon,
      currency: "USD",
      showVolume: true,
      market: "crypto",
    };
  }
  const intlIdx = INTL_INDEX_UI[raw];
  if (intlIdx) {
    return {
      routingClass: "international",
      canonicalSymbol: raw,
      chartApiSymbol: intlIdx.api,
      currency: intlIdx.currency,
      showVolume: false,
      market: "index",
    };
  }
  const intl = canonicalizeInternational(raw);
  if (intl) {
    return {
      routingClass: "international",
      canonicalSymbol: intl,
      chartApiSymbol: intl,
      currency: suffixCurrency(intl) || "USD",
      showVolume: true,
      market: intl.endsWith(".L") || intl.endsWith(".XETRA") || intl.endsWith(".DE") || intl.endsWith(".PA")
        ? "europe"
        : "asia",
    };
  }
  if (US_INDEX_UI.has(raw) || raw.startsWith("^")) {
    return {
      routingClass: "us_equity_index",
      canonicalSymbol: raw,
      chartApiSymbol: raw,
      currency: "USD",
      showVolume: false,
      market: "index",
    };
  }
  if (isMoexSymbol(raw)) {
    return {
      routingClass: "us_equity_index",
      canonicalSymbol: raw.replace(/\.ME$/, ""),
      chartApiSymbol: raw.replace(/\.ME$/, ""),
      currency: "RUB",
      showVolume: raw !== "IMOEX" && raw !== "RTSI",
      market: "moex",
    };
  }
  return {
    routingClass: "us_equity_index",
    canonicalSymbol: raw,
    chartApiSymbol: raw,
    currency: "USD",
    showVolume: true,
    market: "us",
  };
}

export function chartApiSymbol(symbol: string): string {
  return classifySymbol(symbol).chartApiSymbol;
}
