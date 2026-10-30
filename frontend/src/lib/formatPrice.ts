/** Format a price with an explicit currency — never assume USD. */

const SYMBOLS: Record<string, string> = {
  USD: "$",
  EUR: "€",
  GBP: "£",
  JPY: "¥",
  CNY: "¥",
  KRW: "₩",
  HKD: "HK$",
  TWD: "NT$",
  CHF: "CHF ",
  RUB: "₽",
  AUD: "A$",
  CAD: "C$",
  SGD: "S$",
  INR: "₹",
};

export function currencySymbol(code?: string | null): string {
  const c = (code || "").trim().toUpperCase();
  return SYMBOLS[c] || "";
}

export function fmtPrice(
  n: number | null | undefined,
  currency?: string | null,
  digits = 2,
): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const code = (currency || "").trim().toUpperCase();
  const fraction = code === "JPY" || code === "KRW" ? 0 : digits;
  const num = n.toLocaleString("en-US", {
    minimumFractionDigits: fraction,
    maximumFractionDigits: fraction,
  });
  const sym = currencySymbol(code);
  if (sym) return `${sym}${num}`;
  if (code) return `${num} ${code}`;
  return num;
}
