/** FMP ratio/yield fields: 0.25 → 25%. Values already >1 stay as percent. */
export function formatFmpShare(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const pct = Math.abs(value) <= 1 ? value * 100 : value;
  return `${pct.toFixed(1)}%`;
}

/**
 * FMP ROE/ROA/ROIC: 0.28 → 28%, 1.47 → 147%.
 * Already-percent figures (|v| > 2) are left as-is.
 */
export function formatFmpReturnOn(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const pct = Math.abs(value) <= 2 ? value * 100 : value;
  return `${pct.toFixed(1)}%`;
}
