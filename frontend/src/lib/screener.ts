import type { MarketScreenerParams, MarketScreenerRow } from "@/lib/api";

export type ScreenerSortKey = "symbol" | "name" | "price" | "market_cap" | "beta" | "volume" | "pe" | "volatility" | "es_975";

export interface ScreenerDraft {
  country: string;
  sector: string;
  industry: string;
  exchange: string;
  mcapMin: string;
  mcapMax: string;
  priceMin: string;
  priceMax: string;
  betaMin: string;
  volMin: string;
  esMin: string;
  volumeMin: string;
  peMax: string;
  dividendMin: string;
  isEtf: boolean;
  limit: string;
}

export const DEFAULT_SCREENER_DRAFT: ScreenerDraft = {
  country: "US",
  sector: "",
  industry: "",
  exchange: "",
  mcapMin: "10000000000",
  mcapMax: "",
  priceMin: "",
  priceMax: "",
  betaMin: "",
  volMin: "",
  esMin: "",
  volumeMin: "",
  peMax: "",
  dividendMin: "",
  isEtf: false,
  limit: "50",
};

export const SCREENER_PRESETS: Array<{ id: string; label: string; draft: Partial<ScreenerDraft> }> = [
  { id: "us-mega", label: "Гиганты США", draft: { country: "US", sector: "", mcapMin: "200000000000", isEtf: false } },
  { id: "us-tech", label: "Технологии США", draft: { country: "US", sector: "Technology", mcapMin: "10000000000", isEtf: false } },
  { id: "ru-all", label: "Акции России", draft: { country: "RU", sector: "", mcapMin: "", isEtf: false } },
  { id: "dividend", label: "Дивиденды от 2%", draft: { country: "US", dividendMin: "2", mcapMin: "5000000000", isEtf: false } },
  { id: "high-beta", label: "Сильнее рынка (бета от 1,5)", draft: { country: "US", betaMin: "1.5", mcapMin: "2000000000", isEtf: false } },
  { id: "etf", label: "Фонды США (ETF)", draft: { country: "US", sector: "", mcapMin: "", isEtf: true } },
];

export const SCREENER_COUNTRIES: Array<{ value: string; label: string }> = [
  { value: "", label: "Все рынки" },
  { value: "US", label: "США" },
  { value: "RU", label: "Россия" },
  { value: "GB", label: "Великобритания" },
  { value: "DE", label: "Германия" },
  { value: "JP", label: "Япония" },
  { value: "CN", label: "Китай" },
];

export const SCREENER_SECTORS: Array<{ value: string; label: string }> = [
  { value: "", label: "Все отрасли" },
  { value: "Technology", label: "Технологии" },
  { value: "Healthcare", label: "Здравоохранение" },
  { value: "Financial Services", label: "Финансы" },
  { value: "Consumer Cyclical", label: "Товары и услуги" },
  { value: "Consumer Defensive", label: "Товары первой необходимости" },
  { value: "Industrials", label: "Промышленность" },
  { value: "Energy", label: "Энергетика" },
  { value: "Basic Materials", label: "Сырьё и материалы" },
  { value: "Communication Services", label: "Связь и медиа" },
  { value: "Utilities", label: "Коммунальные услуги" },
  { value: "Real Estate", label: "Недвижимость" },
];

export const sectorLabel = (raw: string | null | undefined): string =>
  SCREENER_SECTORS.find((s) => s.value && s.value === raw)?.label ?? raw ?? "—";

/** Company size buckets → market-cap bounds (USD). */
export const SCREENER_SIZES: Array<{ id: string; label: string; min: string; max: string }> = [
  { id: "any", label: "Любой размер", min: "", max: "" },
  { id: "mega", label: "Гиганты (от $200 млрд)", min: "200000000000", max: "" },
  { id: "large", label: "Крупные (от $10 млрд)", min: "10000000000", max: "" },
  { id: "mid", label: "Средние ($2–10 млрд)", min: "2000000000", max: "10000000000" },
  { id: "small", label: "Небольшие (до $2 млрд)", min: "", max: "2000000000" },
];

export function sizeIdOf(draft: Pick<ScreenerDraft, "mcapMin" | "mcapMax">): string {
  return SCREENER_SIZES.find((s) => s.min === draft.mcapMin && s.max === draft.mcapMax)?.id ?? "custom";
}

function numOrUndef(raw: string): number | undefined {
  const trimmed = raw.trim();
  if (!trimmed) return undefined;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : undefined;
}

export function draftToScreenerParams(draft: ScreenerDraft): MarketScreenerParams {
  const limit = Math.min(100, Math.max(1, numOrUndef(draft.limit) ?? 50));
  return {
    country: draft.country.trim() || undefined,
    sector: draft.sector.trim() || undefined,
    industry: draft.industry.trim() || undefined,
    exchange: draft.exchange.trim() || undefined,
    marketCapMoreThan: numOrUndef(draft.mcapMin),
    marketCapLowerThan: numOrUndef(draft.mcapMax),
    priceMoreThan: numOrUndef(draft.priceMin),
    priceLowerThan: numOrUndef(draft.priceMax),
    betaMoreThan: numOrUndef(draft.betaMin),
    volMoreThan: numOrUndef(draft.volMin),
    esMoreThan: numOrUndef(draft.esMin),
    volumeMoreThan: numOrUndef(draft.volumeMin),
    peLowerThan: numOrUndef(draft.peMax),
    dividendMoreThan: numOrUndef(draft.dividendMin),
    isEtf: draft.isEtf || undefined,
    isActivelyTrading: true,
    limit,
  };
}

export function sortScreenerRows(
  rows: MarketScreenerRow[],
  key: ScreenerSortKey,
  dir: "asc" | "desc",
): MarketScreenerRow[] {
  const sign = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = a[key];
    const bv = b[key];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === "string" && typeof bv === "string") {
      return av.localeCompare(bv) * sign;
    }
    return (Number(av) - Number(bv)) * sign;
  });
}

export function terminalHrefForTicker(symbol: string, isStaff: boolean): string {
  const q = encodeURIComponent(symbol.toUpperCase());
  return isStaff ? `/terminal?symbol=${q}` : `/forecasting?symbol=${q}`;
}
