"use client";

import Link from "next/link";
import { RefreshCw } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { WatchlistRowCard } from "./WatchlistRowCard";
import { UniverseSearchField } from "@/components/search/UniverseSearchField";
import { useEffectiveWatchlist, WATCHLIST_QUERY_KEY } from "@/hooks/useEffectiveWatchlist";
import { useWatchlistQuotes } from "@/hooks/useWatchlistQuotes";
import { Spinner } from "@/components/ui";

interface MobileWatchlistSectionProps {
  selectedTicker: string;
  onSelectTicker: (ticker: string) => void;
}

export function MobileWatchlistSection({
  selectedTicker,
  onSelectTicker,
}: MobileWatchlistSectionProps) {
  const queryClient = useQueryClient();
  const { tickers, entries, isLoading, refetch, isFetching } = useEffectiveWatchlist();
  const { bySymbol, isLoading: quotesLoading } = useWatchlistQuotes(tickers, 8);

  const showSpinner = isLoading && tickers.length === 0;

  return (
    <div className="space-y-2">
      <UniverseSearchField
        compact
        placeholder="Тикер или название компании…"
        onPick={onSelectTicker}
      />
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs uppercase text-qa-muted font-bold tracking-wide">Избранное</h3>
        <div className="flex items-center gap-2">
          {quotesLoading && <Spinner size={14} />}
          <button
            type="button"
            onClick={() => {
              queryClient.invalidateQueries({ queryKey: WATCHLIST_QUERY_KEY });
              void refetch();
            }}
            disabled={isFetching}
            className="p-2 min-w-[44px] min-h-[44px] flex items-center justify-center text-qa-muted hover:text-qa-text disabled:opacity-50"
            aria-label="Обновить избранное"
          >
            <RefreshCw size={14} className={isFetching ? "animate-spin" : undefined} />
          </button>
          <Link
            href="/operator/watchlist"
            className="text-[10px] uppercase tracking-wide text-terminal-accent min-h-[44px] flex items-center"
          >
            Все →
          </Link>
        </div>
      </div>

      {showSpinner ? (
        <div className="flex justify-center py-6">
          <Spinner size={20} />
        </div>
      ) : (
        tickers.slice(0, 8).map((symbol) => {
          const entry = entries.find((e) => e.symbol === symbol);
          const quote = bySymbol.get(symbol);
          return (
            <WatchlistRowCard
              key={symbol}
              symbol={symbol}
              label={entry?.label_ru || entry?.label}
              price={quote?.price}
              changePct={quote?.changePct}
              volume={quote?.volume}
              freshnessLabel={quote?.freshnessLabel}
              selected={selectedTicker === symbol}
              onSelect={onSelectTicker}
            />
          );
        })
      )}
    </div>
  );
}
