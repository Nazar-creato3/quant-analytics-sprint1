"use client";

import { useMemo } from "react";
import { clsx } from "clsx";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { DirectDealsRangeSlider } from "@/components/direct-deals/DirectDealsRangeSlider";
import { MarketSessionBadge } from "@/components/direct-deals/MarketSessionBadge";
import { useEffectiveWatchlist } from "@/hooks/useEffectiveWatchlist";
import { resolveDirectDealsWatchGroup } from "@/lib/direct-deals-watchlist-groups";

export interface QuoteView {
  price: number | null;
  bid: number | null;
  ask: number | null;
  changePct: number | null;
  volume: number | null;
  high: number | null;
  low: number | null;
  asOf: string | null;
  stale: boolean;
  error: string | null;
  week52High?: number | null;
  week52Low?: number | null;
  session?: string | null;
  market?: string | null;
}

function fmt(n: number | null, digits = 2): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function DirectDealsQuoteHeader({ symbol, quote, loading }: {
  symbol: string;
  quote: QuoteView;
  loading?: boolean;
}) {
  const { entries } = useEffectiveWatchlist();
  const entry = useMemo(
    () => entries.find((e) => e.symbol.toUpperCase() === symbol.toUpperCase()),
    [entries, symbol],
  );

  const sessionHint = useMemo(() => {
    if (quote.session) return quote.session;
    const group = resolveDirectDealsWatchGroup(symbol, entry);
    if (group === "crypto") return "open";
    return entry?.market?.includes("MOEX") ? "closed" : null;
  }, [quote.session, symbol, entry]);

  const spread =
    quote.bid != null && quote.ask != null && quote.bid > 0
      ? quote.ask - quote.bid
      : null;

  return (
    <div className="rounded-lg border border-qa-border bg-qa-panel px-4 py-3 shrink-0">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-lg font-bold font-mono text-white">{symbol}</h1>
            <MarketSessionBadge session={sessionHint} market={quote.market ?? entry?.market} />
            {loading && <RefreshCw size={14} className="animate-spin text-qa-muted" />}
            {quote.stale && (
              <span className="text-[10px] uppercase px-1.5 py-0.5 rounded border border-qa-accent-border text-qa-warning">
                Устарело
              </span>
            )}
          </div>
          <div className="flex items-baseline gap-3 mt-1">
            <span className="text-2xl font-bold tabular-nums text-white">{fmt(quote.price)}</span>
            {quote.changePct != null && (
              <span
                className={clsx(
                  "text-sm font-semibold tabular-nums",
                  quote.changePct >= 0 ? "text-terminal-up" : "text-terminal-down",
                )}
              >
                {quote.changePct >= 0 ? "+" : ""}
                {quote.changePct.toFixed(2)}%
              </span>
            )}
          </div>
          {quote.asOf && (
            <p className="text-[10px] text-qa-muted mt-1">
              Updated {formatDistanceToNow(new Date(quote.asOf), { addSuffix: true })}
            </p>
          )}

          <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-xl">
            <DirectDealsRangeSlider
              label="Дневной диапазон"
              low={quote.low}
              high={quote.high}
              current={quote.price}
            />
            <DirectDealsRangeSlider
              label="52 недели"
              low={quote.week52Low ?? null}
              high={quote.week52High ?? null}
              current={quote.price}
            />
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-1 text-[11px]">
          <div>
            <span className="text-qa-muted block">Покупка</span>
            <span className="text-terminal-up font-mono tabular-nums">{fmt(quote.bid)}</span>
          </div>
          <div>
            <span className="text-qa-muted block">Продажа</span>
            <span className="text-terminal-down font-mono tabular-nums">{fmt(quote.ask)}</span>
          </div>
          <div>
            <span className="text-qa-muted block">Спред</span>
            <span className="text-qa-text font-mono tabular-nums">{spread != null ? fmt(spread, 4) : "—"}</span>
          </div>
          <div>
            <span className="text-qa-muted block">Объём 24ч</span>
            <span className="text-qa-text font-mono tabular-nums">
              {quote.volume != null ? quote.volume.toLocaleString(undefined, { maximumFractionDigits: 0 }) : "—"}
            </span>
          </div>
          <div>
            <span className="text-qa-muted block">Макс. 24ч</span>
            <span className="text-qa-text font-mono tabular-nums">{fmt(quote.high)}</span>
          </div>
          <div>
            <span className="text-qa-muted block">Мин. 24ч</span>
            <span className="text-qa-text font-mono tabular-nums">{fmt(quote.low)}</span>
          </div>
        </div>
      </div>

      {quote.error && (
        <div className="mt-2 flex items-start gap-1.5 text-[11px] text-qa-warning">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
          {quote.error}
        </div>
      )}
    </div>
  );
}
