/** Home chart ticker: never invent a symbol like AAPL. */
export function resolveHomeTicker(active?: string | null, fromPosition?: string | null): string {
  const chosen = (active || "").trim() || (fromPosition || "").trim();
  return chosen;
}
