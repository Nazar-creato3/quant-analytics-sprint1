/** Price/qty for act and pretrade preview. Never invent 100 or 1. */

export function quoteToPrice(quote: Record<string, unknown> | undefined | null): string | null {
  if (!quote) return null;
  const raw = quote.last ?? quote.price ?? quote.last_price ?? quote.close;
  if (raw == null || raw === "") return null;
  const n = typeof raw === "number" ? raw : Number(String(raw).replace(",", "."));
  if (!Number.isFinite(n) || n <= 0) return null;
  return String(n);
}

export function parseQty(raw: string): string | null {
  const n = Number(String(raw).replace(",", "."));
  if (!Number.isFinite(n) || n <= 0) return null;
  return String(n);
}

export function bookModeLabel(mode: string): string {
  return mode === "live" ? "Боевой" : "Учебный";
}

export const PRETRADE_BLOCK_LABELS: Record<string, string> = {
  factors: "Факторы",
  stress_rate: "Ставка",
  futures: "Срочный рынок",
  goals: "Цели",
  bonds: "Облигации",
  income: "Выплаты",
  look_through: "Состав фондов",
  liquidity: "Ликвидность",
};

export const RISK_TOLERANCE_OPTIONS = [
  { value: "conservative", label: "консервативный" },
  { value: "moderate", label: "умеренный" },
  { value: "aggressive", label: "высокий" },
] as const;

export const HORIZON_OPTIONS = [
  { value: "1y", label: "1 год" },
  { value: "3y", label: "3 года" },
  { value: "5y", label: "5 лет" },
] as const;
