"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { clsx } from "clsx";
import type { OrderBookLevel, OrderBookSnapshot } from "@/types";
import { OrderBookSessionBanner } from "@/components/orders/OrderBookSessionBanner";
import { AdminOnlyNotice } from "@/components/shared/AdminOnlyNotice";
import {
  orderBookAdminDiagnostics,
  orderBookUserFacingMessage,
} from "@/lib/order-book-messages";

interface OrderBookDepthProps {
  book: OrderBookSnapshot;
  limitPrice?: number;
  side: "buy" | "sell";
  depth?: number;
  animated?: boolean;
  onSelectPrice?: (price: number) => void;
}

interface DisplayLevel extends OrderBookLevel {
  total: number;
  pct: number;
}

function DepthUnavailableNotice({ book }: { book: OrderBookSnapshot }) {
  const userMessage = orderBookUserFacingMessage(book);
  const adminDiagnostics = orderBookAdminDiagnostics(book);

  if (!userMessage && !adminDiagnostics) return null;

  return (
    <div className="mb-2 text-center space-y-0.5">
      {userMessage && (
        <p className="text-warning/90 text-[10px] leading-snug px-1">{userMessage}</p>
      )}
      <AdminOnlyNotice>
        {adminDiagnostics && (
          <details className="text-qa-muted text-[9px] px-1 leading-snug">
            <summary className="cursor-pointer select-none opacity-70 hover:opacity-100">
              Источники стакана (для админа)
            </summary>
            <p className="mt-1 break-words text-left">{adminDiagnostics}</p>
          </details>
        )}
      </AdminOnlyNotice>
    </div>
  );
}

function levelKey(side: "bid" | "ask", price: number): string {
  return `${side}-${price}`;
}

function useFlashKeys(
  levels: OrderBookLevel[],
  side: "bid" | "ask",
  enabled: boolean,
): Set<string> {
  const prev = useRef<Map<string, OrderBookLevel>>(new Map());
  const [flashing, setFlashing] = useState<Set<string>>(() => new Set());

  useEffect(() => {
    if (!enabled) return;
    const next = new Map<string, OrderBookLevel>();
    const changed = new Set<string>();

    for (const lvl of levels) {
      const key = levelKey(side, lvl.price);
      next.set(key, lvl);
      const old = prev.current.get(key);
      if (old && (old.size !== lvl.size || old.price !== lvl.price)) {
        changed.add(key);
      }
    }

    for (const key of prev.current.keys()) {
      if (!next.has(key)) changed.add(key);
    }

    prev.current = next;
    if (changed.size === 0) return;

    setFlashing(new Set(changed));
    const t = window.setTimeout(() => setFlashing(new Set()), 500);
    return () => window.clearTimeout(t);
  }, [levels, side, enabled]);

  return flashing;
}

function fmtPrice(price: number): string {
  if (price >= 1000) return price.toFixed(2);
  if (price >= 1) return price.toFixed(4);
  if (price >= 0.01) return price.toFixed(5);
  return price.toFixed(8);
}

function fmtSize(size: number): string {
  if (size <= 0) return "—";
  if (size >= 1_000_000) return `${(size / 1_000_000).toFixed(2)}M`;
  if (size >= 1_000) return `${(size / 1_000).toFixed(2)}K`;
  if (size >= 1) return size.toFixed(2);
  return size.toFixed(6);
}

function fmtTotal(total: number): string {
  if (total <= 0) return "—";
  if (total >= 1_000_000) return `${(total / 1_000_000).toFixed(2)}M`;
  if (total >= 1_000) return `${(total / 1_000).toFixed(1)}K`;
  return total.toFixed(2);
}

function withCumulative(levels: OrderBookLevel[], sideTotal: number): DisplayLevel[] {
  let running = 0;
  return levels.map((level) => {
    running += level.size;
    return {
      ...level,
      total: running,
      pct: sideTotal > 0 ? (level.size / sideTotal) * 100 : 0,
    };
  });
}

function aggregateLevels(
  levels: OrderBookLevel[],
  tick: number,
  side: "bid" | "ask",
): OrderBookLevel[] {
  if (!(tick > 0) || levels.length === 0) return levels;
  const buckets = new Map<number, number>();
  for (const lvl of levels) {
    if (!(lvl.price > 0) || !(lvl.size > 0)) continue;
    const key =
      side === "bid"
        ? Math.floor(lvl.price / tick + 1e-12) * tick
        : Math.ceil(lvl.price / tick - 1e-12) * tick;
    const rounded = Math.round(key / tick) * tick;
    buckets.set(rounded, (buckets.get(rounded) ?? 0) + lvl.size);
  }
  const out = Array.from(buckets.entries()).map(([price, size]) => ({ price, size }));
  out.sort((a, b) => (side === "bid" ? b.price - a.price : a.price - b.price));
  return out;
}

function detectNativeTick(levels: OrderBookLevel[]): number {
  const prices = levels.map((l) => l.price).filter((p) => p > 0).sort((a, b) => a - b);
  let minDiff = Infinity;
  for (let i = 1; i < prices.length; i++) {
    const d = Math.abs(prices[i]! - prices[i - 1]!);
    if (d > 1e-12 && d < minDiff) minDiff = d;
  }
  if (!Number.isFinite(minDiff) || minDiff === Infinity) return 0.01;
  // Snap to clean decimals
  const candidates = [0.00001, 0.0001, 0.001, 0.01, 0.05, 0.1, 0.5, 1, 5, 10, 50, 100];
  let best = candidates[0]!;
  let bestErr = Math.abs(minDiff - best);
  for (const c of candidates) {
    const err = Math.abs(minDiff - c);
    if (err < bestErr) {
      best = c;
      bestErr = err;
    }
  }
  return best;
}

function suggestTickSteps(mid: number | null | undefined, nativeTick?: number): number[] {
  const base = nativeTick && nativeTick > 0 ? nativeTick : 0.01;
  const p = mid && mid > 0 ? mid : 100;
  const mults = p >= 1000 ? [1, 10, 100, 1000, 5000, 10000] : p >= 100 ? [1, 10, 50, 100, 500] : [1, 10, 100, 1000];
  const steps = mults.map((m) => Number((base * m).toPrecision(8)));
  const uniq = Array.from(new Set([base, ...steps])).filter((t) => t > 0).sort((a, b) => a - b);
  return uniq;
}

function fmtTick(tick: number): string {
  if (tick >= 1) return String(tick);
  return tick.toFixed(8).replace(/\.?0+$/, "");
}

function DepthRow({
  level,
  side,
  maxSize,
  flash,
  onClick,
}: {
  level: DisplayLevel;
  side: "bid" | "ask";
  maxSize: number;
  flash: boolean;
  onClick?: () => void;
}) {
  const widthPct = level.size > 0 ? (level.size / maxSize) * 100 : 0;
  const isBid = side === "bid";

  const content = (
    <>
      <span
        className={clsx(
          "absolute inset-y-0 transition-[width] duration-200 ease-out",
          isBid ? "right-0 depth-bar-bid" : "left-0 depth-bar-ask",
        )}
        style={{ width: `${widthPct}%` }}
      />
      <span
        className={clsx(
          "absolute inset-0 pointer-events-none transition-opacity duration-500",
          flash ? "opacity-100 depth-flash" : "opacity-0",
        )}
      />
      <span className={clsx("relative tabular-nums", isBid ? "text-terminal-up" : "text-terminal-down")}>
        {fmtPrice(level.price)}
      </span>
      <span className="relative text-qa-muted tabular-nums text-right">{fmtSize(level.size)}</span>
      <span className="relative text-qa-muted tabular-nums text-right">{fmtTotal(level.total)}</span>
    </>
  );

  const className = clsx(
    "relative grid grid-cols-[1fr_0.75fr_0.75fr] px-1.5 py-0.5 rounded overflow-hidden text-[10px] font-mono",
    onClick && "cursor-pointer hover:bg-[var(--qa-hover)]",
  );

  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={clsx(className, "w-full text-left")}>
        {content}
      </button>
    );
  }

  return <div className={className}>{content}</div>;
}

function BuySellRatioBar({ bids, asks }: { bids: OrderBookLevel[]; asks: OrderBookLevel[] }) {
  const { bidPct, askPct, bidVol, askVol } = useMemo(() => {
    const bidVol = bids.reduce((s, l) => s + l.size, 0);
    const askVol = asks.reduce((s, l) => s + l.size, 0);
    const total = bidVol + askVol || 1;
    return {
      bidVol,
      askVol,
      bidPct: (bidVol / total) * 100,
      askPct: (askVol / total) * 100,
    };
  }, [bids, asks]);

  if (bidVol <= 0 && askVol <= 0) return null;

  return (
    <div className="mt-2 pt-2 border-t border-qa-border space-y-1">
      <div className="flex h-2 rounded-full overflow-hidden bg-qa-panel-secondary">
        <div
          className="h-full depth-bar-ratio-bid transition-[width] duration-300 ease-out"
          style={{ width: `${bidPct}%` }}
        />
        <div
          className="h-full depth-bar-ratio-ask transition-[width] duration-300 ease-out"
          style={{ width: `${askPct}%` }}
        />
      </div>
      <div className="flex justify-between text-[10px] font-mono tabular-nums">
        <span className="text-terminal-up">{bidPct.toFixed(2)}% B · {fmtSize(bidVol)}</span>
        <span className="text-terminal-down">{askPct.toFixed(2)}% S · {fmtSize(askVol)}</span>
      </div>
    </div>
  );
}

export function OrderBookDepth({
  book,
  limitPrice,
  side,
  depth = 10,
  animated = true,
  onSelectPrice,
}: OrderBookDepthProps) {
  const depthAvailable = book.depth_available !== false;
  const nativeTick = useMemo(
    () => detectNativeTick([...book.bids, ...book.asks]),
    [book.bids, book.asks],
  );
  const tickOptions = useMemo(
    () => suggestTickSteps(book.mid_price, nativeTick),
    [book.mid_price, nativeTick],
  );
  const [tick, setTick] = useState(() => tickOptions[0] ?? nativeTick ?? 0.01);

  useEffect(() => {
    if (!tickOptions.includes(tick)) {
      setTick(tickOptions[0] ?? 0.01);
    }
  }, [tickOptions, tick]);

  const rawBids = useMemo(() => {
    return aggregateLevels(book.bids, tick, "bid").slice(0, depth);
  }, [book.bids, depth, tick]);

  const rawAsks = useMemo(() => {
    return [...aggregateLevels(book.asks, tick, "ask").slice(0, depth)].sort(
      (a, b) => b.price - a.price,
    );
  }, [book.asks, depth, tick]);

  const bidFlashes = useFlashKeys(rawBids, "bid", animated);
  const askFlashes = useFlashKeys(rawAsks, "ask", animated);

  const showReferenceOnly =
    !depthAvailable && book.mid_price != null && rawBids.length === 0 && rawAsks.length === 0;

  if (showReferenceOnly) {
    return (
      <div className="text-[10px] space-y-2 py-4 text-center">
        <OrderBookSessionBanner book={book} />
        <p className="text-lg font-mono tabular-nums text-qa-text">{fmtPrice(book.mid_price!)}</p>
        <DepthUnavailableNotice book={book} />
        <AdminOnlyNotice>
          {book.source && <p className="text-qa-muted text-[10px]">{book.source}</p>}
        </AdminOnlyNotice>
      </div>
    );
  }

  const bidVol = rawBids.reduce((s, l) => s + (l.size > 0 ? l.size : 0), 0);
  const askVol = rawAsks.reduce((s, l) => s + (l.size > 0 ? l.size : 0), 0);
  const bids = withCumulative(rawBids, bidVol);
  const asks = withCumulative(rawAsks, askVol);

  const maxSize = Math.max(
    ...bids.map((b) => b.size),
    ...asks.map((a) => a.size),
    1,
  );

  const bestBid = bids[0]?.price;
  const bestAsk = asks[asks.length - 1]?.price;

  return (
    <div className="text-[10px]">
      <OrderBookSessionBanner book={book} />
      {!depthAvailable && <DepthUnavailableNotice book={book} />}
      <div className="flex justify-between items-center text-qa-muted mb-1 px-0.5 gap-2">
        <span className="uppercase tracking-wide">Стакан</span>
        <label className="flex items-center gap-1 text-[9px] normal-case tracking-normal">
          <span className="text-qa-muted">Шаг</span>
          <select
            value={String(tick)}
            onChange={(e) => setTick(Number(e.target.value))}
            className="bg-cockpit-panel border border-qa-border rounded px-1 py-0.5 text-[10px] font-mono text-qa-text"
            title="Группировка уровней стакана"
            aria-label="Шаг цены стакана"
          >
            {tickOptions.map((t) => (
              <option key={t} value={String(t)}>
                {fmtTick(t)}
              </option>
            ))}
          </select>
        </label>
        {book.spread_bps != null && (
          <span className="tabular-nums">Spread {book.spread_bps.toFixed(2)} bps</span>
        )}
      </div>

      <div className="grid grid-cols-[1fr_0.75fr_0.75fr] gap-2 text-[9px] text-qa-muted uppercase px-0.5 mb-0.5">
        <span>Цена</span>
        <span className="text-right">Объём</span>
        <span className="text-right">Σ</span>
      </div>

      <div className="space-y-0.5">
        {asks.map((level) => (
          <DepthRow
            key={`a-${level.price}`}
            level={level}
            side="ask"
            maxSize={maxSize}
            flash={askFlashes.has(levelKey("ask", level.price))}
            onClick={onSelectPrice ? () => onSelectPrice(level.price) : undefined}
          />
        ))}
      </div>

      {(bestBid != null || bestAsk != null) && (
        <div className="my-1 py-1 border-y border-qa-border/60 flex justify-between px-1.5 text-[10px] font-mono tabular-nums">
          <span className="text-terminal-up">{bestBid != null ? fmtPrice(bestBid) : "—"}</span>
          <span className="text-qa-muted">mid {book.mid_price != null ? fmtPrice(book.mid_price) : "—"}</span>
          <span className="text-terminal-down">{bestAsk != null ? fmtPrice(bestAsk) : "—"}</span>
        </div>
      )}

      <div className="space-y-0.5">
        {bids.map((level) => (
          <DepthRow
            key={`b-${level.price}`}
            level={level}
            side="bid"
            maxSize={maxSize}
            flash={bidFlashes.has(levelKey("bid", level.price))}
            onClick={onSelectPrice ? () => onSelectPrice(level.price) : undefined}
          />
        ))}
      </div>

      <BuySellRatioBar bids={rawBids} asks={rawAsks} />

      {limitPrice != null && book.mid_price != null && (
        <div className="mt-1 text-qa-muted px-0.5">
          Your {side} limit vs mid:{" "}
          {(((limitPrice - book.mid_price) / book.mid_price) * 100).toFixed(2)}%
        </div>
      )}
    </div>
  );
}
