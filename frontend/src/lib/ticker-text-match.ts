/** Word-boundary ticker match (META ≠ METALS, C ≠ CALL). */
export function textMatchesTicker(text: string, ticker: string): boolean {
  const t = ticker.trim().toUpperCase();
  if (!t || !text) return false;
  const upper = text.toUpperCase();
  const escaped = t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const token = new RegExp(`(?<![A-Z0-9.])${escaped}(?![A-Z0-9.])`);
  if (token.test(upper)) return true;
  return new RegExp(`\\$${escaped}(?![A-Z0-9.])`).test(upper);
}

export function newsMentionsTicker(
  item: {
    tickers_mentioned?: string[] | null;
    headline?: string | null;
    title?: string | null;
    summary?: string | null;
    description?: string | null;
  },
  ticker: string,
): boolean {
  const want = ticker.trim().toUpperCase();
  if (!want) return false;
  const mentioned = (item.tickers_mentioned ?? []).map((s) => s.trim().toUpperCase()).filter(Boolean);
  if (mentioned.length > 0) return mentioned.includes(want);
  const blob = [item.headline, item.title, item.summary, item.description].filter(Boolean).join(" ");
  return textMatchesTicker(blob, want);
}
