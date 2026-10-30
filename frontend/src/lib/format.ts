/** Amount without a currency sign or K/M suffix. The screen shows the currency separately. */

export function formatUsd(
  value: number | null | undefined,
  opts?: { compact?: boolean; decimals?: number },
): string {
  if (value == null || Number.isNaN(value)) return "—";

  const { decimals = 0 } = opts ?? {};
  return value.toLocaleString("ru-RU", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}
