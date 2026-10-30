/**
 * Live pre-submit order economics: walk the book, estimate fees, flag fat-finger.
 * Platform never extends credit — figures are venue-relay estimates only.
 */

export const FAT_FINGER_NOTIONAL_USD = 25_000;
export const FAT_FINGER_BALANCE_FRACTION = 0.25;
/** Fallback taker bps when venue schedule is unknown (matches backend `_fees_usd`). */
export const DEFAULT_TAKER_FEE_RATE = 0.001;

export type BookLevel = { price: number; size: number };

export type OrderPreviewSide = "buy" | "sell";
export type OrderPreviewType = "market" | "limit" | "stop" | "stop_limit" | "oco" | "trailing_stop";

export interface OrderPreviewInput {
  side: OrderPreviewSide;
  orderType: OrderPreviewType;
  quantity: number;
  limitPrice?: number | null;
  bids: BookLevel[];
  asks: BookLevel[];
  feeRate?: number;
  availableBalanceUsd?: number;
}

export interface OrderPreview {
  fillLow: number | null;
  fillHigh: number | null;
  avgPrice: number | null;
  filledQty: number;
  complete: boolean;
  feeUsd: number;
  /** Debit (buy) or credit (sell), including fee. */
  totalUsd: number;
  notionalUsd: number;
  fatFinger: boolean;
  wouldTake: boolean;
  label: string;
}

function levelsForSide(side: OrderPreviewSide, bids: BookLevel[], asks: BookLevel[]): BookLevel[] {
  if (side === "buy") {
    return [...asks].filter((l) => l.price > 0 && l.size > 0).sort((a, b) => a.price - b.price);
  }
  return [...bids].filter((l) => l.price > 0 && l.size > 0).sort((a, b) => b.price - a.price);
}

export function walkBookFill(
  levels: BookLevel[],
  quantity: number,
): { filledQty: number; notional: number; low: number | null; high: number | null; avg: number | null; complete: boolean } {
  let remaining = quantity;
  let notional = 0;
  let low: number | null = null;
  let high: number | null = null;
  for (const lvl of levels) {
    if (remaining <= 0) break;
    const take = Math.min(remaining, lvl.size);
    notional += take * lvl.price;
    remaining -= take;
    low = low == null ? lvl.price : Math.min(low, lvl.price);
    high = high == null ? lvl.price : Math.max(high, lvl.price);
  }
  const filledQty = quantity - remaining;
  return {
    filledQty,
    notional,
    low,
    high,
    avg: filledQty > 0 ? notional / filledQty : null,
    complete: remaining <= 1e-12,
  };
}

export function limitWouldTake(
  side: OrderPreviewSide,
  limitPrice: number,
  bids: BookLevel[],
  asks: BookLevel[],
): boolean {
  if (!(limitPrice > 0)) return false;
  const bestAsk = asks.filter((l) => l.size > 0).sort((a, b) => a.price - b.price)[0]?.price;
  const bestBid = bids.filter((l) => l.size > 0).sort((a, b) => b.price - a.price)[0]?.price;
  if (side === "buy") return bestAsk != null && limitPrice >= bestAsk;
  return bestBid != null && limitPrice <= bestBid;
}

export function isFatFinger(notionalUsd: number, availableBalanceUsd = 0): boolean {
  if (notionalUsd >= FAT_FINGER_NOTIONAL_USD) return true;
  if (availableBalanceUsd > 0 && notionalUsd >= availableBalanceUsd * FAT_FINGER_BALANCE_FRACTION) {
    return true;
  }
  return false;
}

export function estimateOrderPreview(input: OrderPreviewInput): OrderPreview | null {
  const qty = input.quantity;
  if (!(qty > 0)) return null;

  const feeRate = input.feeRate ?? DEFAULT_TAKER_FEE_RATE;
  const isMarket = input.orderType === "market" || input.orderType === "stop" || input.orderType === "trailing_stop";
  const limit = input.limitPrice ?? null;

  let fillLow: number | null = null;
  let fillHigh: number | null = null;
  let avgPrice: number | null = null;
  let filledQty = qty;
  let complete = true;
  let notionalUsd = 0;
  let wouldTake = false;

  if (isMarket) {
    const walk = walkBookFill(levelsForSide(input.side, input.bids, input.asks), qty);
    fillLow = walk.low;
    fillHigh = walk.high;
    avgPrice = walk.avg;
    filledQty = walk.filledQty;
    complete = walk.complete;
    notionalUsd = walk.notional;
    wouldTake = true;
  } else if (limit && limit > 0) {
    wouldTake = limitWouldTake(input.side, limit, input.bids, input.asks);
    if (wouldTake) {
      const walk = walkBookFill(levelsForSide(input.side, input.bids, input.asks), qty);
      fillLow = walk.low;
      fillHigh = Math.max(walk.high ?? limit, limit);
      avgPrice = walk.avg ?? limit;
      filledQty = walk.filledQty || qty;
      complete = walk.complete;
      notionalUsd = walk.notional || limit * qty;
    } else {
      fillLow = limit;
      fillHigh = limit;
      avgPrice = limit;
      notionalUsd = limit * qty;
    }
  } else {
    return null;
  }

  const feeUsd = notionalUsd * feeRate;
  const totalUsd = input.side === "buy" ? notionalUsd + feeUsd : Math.max(0, notionalUsd - feeUsd);
  const typeLabel =
    input.orderType === "market"
      ? "по рынку"
      : input.orderType === "limit"
        ? `лимит ${limit}`
        : input.orderType.replace("_", "-");

  return {
    fillLow,
    fillHigh,
    avgPrice,
    filledQty,
    complete,
    feeUsd,
    totalUsd,
    notionalUsd,
    fatFinger: isFatFinger(notionalUsd, input.availableBalanceUsd ?? 0),
    wouldTake,
    label: `${qty} ${typeLabel}`,
  };
}

export function formatUsd(n: number, digits = 2): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function formatPriceRange(low: number | null, high: number | null): string {
  if (low == null || high == null) return "—";
  if (Math.abs(low - high) < 1e-9) return `$${formatUsd(low, low >= 100 ? 2 : 4)}`;
  return `$${formatUsd(low, low >= 100 ? 2 : 4)} – $${formatUsd(high, high >= 100 ? 2 : 4)}`;
}
