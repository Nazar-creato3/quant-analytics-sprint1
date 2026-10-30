"use client";

import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { MessageCircle, RefreshCw } from "lucide-react";
import {
  filterWatchlistTickers,
  WATCHLIST_FILTERS,
  type WatchlistFilterId,
} from "@/lib/watchlist-filters";
import { useEffectiveWatchlist, WATCHLIST_QUERY_KEY } from "@/hooks/useEffectiveWatchlist";
import { useWatchlistMlSignals } from "@/hooks/useWatchlistMlSignals";
import { formatMlSignal } from "@/lib/ml-forecast-signal";
import { UniverseSearchField } from "@/components/search/UniverseSearchField";
import { CockpitPanelHeader } from "./CockpitPanelHeader";
import { WatchlistTickerChat } from "./WatchlistTickerChat";
import { Spinner } from "@/components/ui";

interface WatchlistSidebarProps {
  selectedTicker: string;
  onSelectTicker: (ticker: string) => void;
}

export function WatchlistSidebar({ selectedTicker, onSelectTicker }: WatchlistSidebarProps) {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<WatchlistFilterId>("all");
  const [chatTicker, setChatTicker] = useState<string | null>(null);

  const { data, tickers: baseTickers, isLoading, refetch, isFetching } = useEffectiveWatchlist();

  const tickers = useMemo(
    () => filterWatchlistTickers(baseTickers, data?.entries, filter),
    [baseTickers, data?.entries, filter],
  );

  const { bySymbol: mlBySym } = useWatchlistMlSignals(tickers);

  const openChat = (ticker: string) => {
    onSelectTicker(ticker);
    setChatTicker(prev => (prev === ticker ? null : ticker));
  };

  return (
    <aside className={clsx(
      "cockpit-sidebar shrink-0 flex flex-col min-h-0 overflow-x-hidden",
      chatTicker ? "w-[280px] min-w-[280px]" : "w-[220px]",
    )}>
      <CockpitPanelHeader
        title="Watchlist"
        badge={tickers.length}
        href="/operator/watchlist"
        action={
          <button
            type="button"
            onClick={() => {
              queryClient.invalidateQueries({ queryKey: WATCHLIST_QUERY_KEY });
              void refetch();
            }}
            disabled={isFetching}
            className="p-1 rounded text-qa-muted hover:text-qa-text disabled:opacity-50"
            title="Обновить избранное"
          >
            <RefreshCw size={12} className={isFetching ? "animate-spin" : undefined} />
          </button>
        }
      />

      <div className="p-2 border-b border-cockpit-border space-y-2">
        <UniverseSearchField
          compact
          placeholder="Тикер или название компании…"
          onPick={(symbol) => onSelectTicker(symbol)}
        />
        <p className="text-[8px] text-qa-muted">Ниже — избранное. Поиск сверху по всем биржам.</p>
        <div className="flex flex-wrap gap-0.5">
          {WATCHLIST_FILTERS.map(f => (
            <button
              key={f.id}
              onClick={() => setFilter(f.id)}
              className={clsx(
                "shrink-0 px-1 py-0.5 rounded text-[9px] font-medium transition-colors",
                filter === f.id
                  ? "bg-cockpit-panel-raised text-qa-text border border-cockpit-border-strong"
                  : "text-qa-muted hover:text-qa-text",
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <div
        className={clsx(
          "overflow-y-auto p-2 space-y-0.5 min-h-0",
          chatTicker ? "flex-[0_0_45%] shrink-0" : "flex-1",
        )}
      >
        {isLoading && !data ? (
          <div className="flex justify-center py-6">
            <Spinner size={18} />
          </div>
        ) : tickers.length === 0 ? (
          <p className="text-[10px] text-qa-muted text-center py-4">
            Нет тикеров по фильтру
          </p>
        ) : (
          tickers.map(t => {
            const ml = formatMlSignal(mlBySym.get(t));
            return (
            <div key={t} className="flex items-center gap-0.5">
              <button
                type="button"
                onClick={() => onSelectTicker(t)}
                className={clsx(
                  "flex-1 min-w-0 text-left px-2 py-1.5 rounded text-xs font-mono transition-colors",
                  t === selectedTicker
                    ? "bg-[var(--qa-active)] text-terminal-accent border border-terminal-accent/40"
                    : "text-qa-muted hover:text-qa-text hover:bg-cockpit-panel border border-transparent",
                )}
              >
                <span className="flex items-center justify-between gap-1">
                  <span className="truncate">{t}</span>
                  <span className={clsx("text-[9px] font-mono shrink-0", ml.cls)} title={ml.title}>
                    {ml.text}
                  </span>
                </span>
              </button>
              <button
                type="button"
                onClick={() => openChat(t)}
                className={clsx(
                  "p-1 rounded shrink-0 transition-colors",
                  chatTicker === t
                    ? "text-terminal-accent bg-[var(--qa-active)]"
                    : "text-qa-muted hover:text-terminal-accent hover:bg-cockpit-panel",
                )}
                title={`Чат по ${t}`}
              >
                <MessageCircle size={11} />
              </button>
            </div>
            );
          })
        )}
      </div>

      {chatTicker && (
        <WatchlistTickerChat symbol={chatTicker} onClose={() => setChatTicker(null)} />
      )}
    </aside>
  );
}
