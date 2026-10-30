/** Frontend catalog helper — same rules as backend resolve for offline fields. */

export type CatalogHit = {
  symbol: string;
  assetId: string;
  venue: string;
  ambiguous?: boolean;
};

export function catalogNormalize(raw: string | null | undefined): CatalogHit {
  const collapsed = (raw ?? "").trim().toUpperCase().replace(/\s+/g, " ");
  if (!collapsed) return { symbol: "AAPL", assetId: "eq:AAPL", venue: "US" };
  if (/^BRK[.\s]B$/.test(collapsed)) return { symbol: "BRK.B", assetId: "eq:BRK.B", venue: "US" };
  if (collapsed.endsWith(".ME")) {
    const bare = collapsed.slice(0, -3);
    return { symbol: bare, assetId: `eq:${bare}`, venue: "MOEX" };
  }
  if (collapsed.endsWith("USDT")) {
    const base = collapsed.slice(0, -4);
    return { symbol: `${base}-USD`, assetId: `crypto:${base}`, venue: "BINANCE" };
  }
  return {
    symbol: collapsed.replace(/\s+/g, "").slice(0, 24),
    assetId: `eq:${collapsed.replace(/\s+/g, "")}`,
    venue: "US",
  };
}
