"use client";

import { useEffect, useMemo, useState } from "react";
import { clsx } from "clsx";
import { ChevronLeft, ChevronRight, RefreshCw, Search } from "lucide-react";
import { useEffectiveWatchlist } from "@/hooks/useEffectiveWatchlist";
import { useWatchlistQuotes } from "@/hooks/useWatchlistQuotes";
import {
  DIRECT_DEALS_WATCH_GROUPS,
  groupWatchlistTickers,
  type DirectDealsWatchGroup,
} from "@/lib/direct-deals-watchlist-groups";
import { formatInstrumentPrice } from "@/lib/instrument-price-format";
import { DirectDealsWatchlistSparkline } from "@/components/direct-deals/DirectDealsWatchlistSparkline";

const SIDEBAR_COLLAPSED_KEY = "direct-deals:sidebar-collapsed";

function fmtPct(n: number | null): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

interface DirectDealsWatchlistSidebarProps {
  selectedSymbol: string;
  onSelectSymbol: (symbol: string) => void;
}

/** Compact asset rail for Deals: ticker + sparkline + price — not a watchlist manager. */
export function DirectDealsWatchlistSidebar({
  selectedSymbol,
  onSelectSymbol,
}: DirectDealsWatchlistSidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [query, setQuery] = useState("");
  const [expandedGroups, setExpandedGroups] = useState<Record<DirectDealsWatchGroup, boolean>>({
    indices: true,
    stocks: true,
    currencies: true,
    crypto: true,
  });

  const { tickers, entries, isFetching, refetch } = useEffectiveWatchlist();
  const grouped = useMemo(() => groupWatchlistTickers(tickers, entries), [tickers, entries]);
  const { bySymbol } = useWatchlistQuotes(tickers, 40);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
    if (stored === "1") setCollapsed(true);
  }, []);

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      if (typeof window !== "undefined") {
        window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, next ? "1" : "0");
      }
      return next;
    });
  };

  const toggleGroup = (id: DirectDealsWatchGroup) => {
    setExpandedGroups((g) => ({ ...g, [id]: !g[id] }));
  };

  const q = query.trim().toUpperCase();
  const flatFiltered = useMemo(() => {
    const all = tickers.filter((s) => !q || s.includes(q));
    return all;
  }, [tickers, q]);

  return (
    <aside
      className={clsx(
        "shrink-0 flex flex-col border-r border-qa-border bg-qa-panel/90 transition-[width] duration-200 sticky top-0 self-start max-h-screen",
        collapsed ? "w-10" : "w-[220px] min-w-[220px]",
      )}
    >
      <div className="flex items-center justify-between px-2 py-2 border-b border-qa-border shrink-0">
        {!collapsed && (
          <span className="text-[10px] font-semibold uppercase tracking-wide text-qa-muted">
            Активы
          </span>
        )}
        <div className="flex items-center gap-0.5 ml-auto">
          {!collapsed && (
            <button
              type="button"
              onClick={() => void refetch()}
              disabled={isFetching}
              className="p-1 rounded text-qa-muted hover:text-qa-text disabled:opacity-50"
              title="Обновить котировки"
            >
              <RefreshCw size={11} className={isFetching ? "animate-spin" : undefined} />
            </button>
          )}
          <button
            type="button"
            onClick={toggleCollapsed}
            className="p-1 rounded text-qa-muted hover:text-qa-text"
            title={collapsed ? "Развернуть" : "Свернуть"}
          >
            {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
          </button>
        </div>
      </div>

      {!collapsed && (
        <>
          <div className="p-2 border-b border-qa-border shrink-0">
            <div className="relative">
              <Search size={11} className="absolute left-2 top-1/2 -translate-y-1/2 text-qa-muted" />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && q) {
                    onSelectSymbol(q);
                  }
                }}
                placeholder="Тикер…"
                className="w-full bg-qa-bg border border-qa-border rounded pl-7 pr-2 py-1.5 text-[11px] text-qa-text placeholder:text-qa-muted focus:outline-none focus:border-qa-border-strong"
              />
            </div>
            <p className="text-[8px] text-qa-muted mt-1.5 px-0.5">
              Список с мини-графиками. Enter — открыть тикер.
            </p>
          </div>

          <div className="flex-1 overflow-y-auto min-h-0 p-1 space-y-1">
            {DIRECT_DEALS_WATCH_GROUPS.map(({ id, label }) => {
              const symbols = grouped[id].filter((s) => !q || s.includes(q));
              if (symbols.length === 0) return null;
              const open = expandedGroups[id];
              return (
                <div key={id}>
                  <button
                    type="button"
                    onClick={() => toggleGroup(id)}
                    className="w-full flex items-center justify-between px-2 py-1 text-[9px] uppercase tracking-wide text-qa-muted hover:text-qa-text"
                  >
                    <span>{label}</span>
                    <span className="tabular-nums">{symbols.length}</span>
                  </button>
                  {open && (
                    <div className="space-y-0.5">
                      {symbols.map((sym, symbolIndex) => {
                        const quote = bySymbol.get(sym);
                        const selected = sym === selectedSymbol.toUpperCase();
                        const up = (quote?.changePct ?? 0) >= 0;
                        return (
                          <button
                            key={sym}
                            type="button"
                            onClick={() => onSelectSymbol(sym)}
                            className={clsx(
                              "w-full text-left px-2 py-1.5 rounded transition-colors",
                              selected
                                ? "bg-[var(--qa-active)] border border-terminal-accent/40"
                                : "border border-transparent hover:bg-[var(--qa-hover)]",
                            )}
                          >
                            <div className="flex items-center gap-1.5 min-w-0">
                              <span
                                className={clsx(
                                  "text-[11px] font-mono truncate shrink-0 w-[46px]",
                                  selected ? "text-terminal-accent" : "text-qa-text",
                                )}
                              >
                                {sym}
                              </span>
                              <DirectDealsWatchlistSparkline
                                ticker={sym}
                                index={symbolIndex}
                                priority={selected}
                              />
                              <div className="ml-auto shrink-0 text-right">
                                <div className="text-[10px] font-mono tabular-nums text-qa-text">
                                  {formatInstrumentPrice(sym, quote?.price ?? null)}
                                </div>
                                <div
                                  className={clsx(
                                    "text-[9px] font-mono tabular-nums",
                                    quote?.changePct == null
                                      ? "text-qa-muted"
                                      : up
                                        ? "text-terminal-up"
                                        : "text-terminal-down",
                                  )}
                                >
                                  {fmtPct(quote?.changePct ?? null)}
                                </div>
                              </div>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
            {flatFiltered.length === 0 ? (
              <p className="text-[10px] text-qa-muted px-2 py-3">Нет тикеров по фильтру</p>
            ) : null}
          </div>
        </>
      )}
    </aside>
  );
}
