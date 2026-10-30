/** URL helpers for Direct Deals prefill from maneuvers or deep links. */

export interface DirectDealsParams {
  symbol?: string;
  maneuverId?: string;
  side?: "buy" | "sell";
}

export function buildDirectDealsUrl(params: DirectDealsParams): string {
  const q = new URLSearchParams();
  if (params.symbol) q.set("symbol", params.symbol.toUpperCase());
  if (params.maneuverId) q.set("maneuver", params.maneuverId);
  if (params.side) q.set("side", params.side);
  const qs = q.toString();
  return qs ? `/direct-deals?${qs}` : "/direct-deals";
}

export function parseDirectDealsSearch(search: string): DirectDealsParams {
  const q = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const symbol = q.get("symbol") || q.get("ticker") || undefined;
  const maneuverId = q.get("maneuver") || q.get("maneuverId") || undefined;
  const sideRaw = q.get("side");
  const side = sideRaw === "buy" || sideRaw === "sell" ? sideRaw : undefined;
  return { symbol: symbol?.toUpperCase(), maneuverId: maneuverId ?? undefined, side };
}

/** Poll intervals for live market data on Direct Deals. */
export const DIRECT_DEALS_POLL = {
  // US L2 is rate-limited; 500ms fan-out caused Polygon/Alpaca/Twelve/Tiingo 429 storms.
  orderBookMs: 4_000,
  quoteMs: 2_000,
  balancesMs: 10_000,
  ordersMs: 5_000,
} as const;
