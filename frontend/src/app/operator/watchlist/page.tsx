"use client";

import { useEffect, useState } from "react";
import { OperatorDetailShell } from "@/components/operator/OperatorDetailShell";
import { TickerSparkline } from "@/components/charts/PriceChart";
import { WatchlistTickerPanel } from "@/components/operator/WatchlistTickerPanel";
import { UniverseSearchField } from "@/components/search/UniverseSearchField";
import { useEffectiveWatchlist } from "@/hooks/useEffectiveWatchlist";
import { Spinner } from "@/components/ui";

export default function OperatorWatchlistPage() {
  const { tickers, isLoading } = useEffectiveWatchlist();
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (!tickers.length) return;
    setSelected(prev => prev ?? tickers[0]);
  }, [tickers]);

  const activeTicker = selected ?? tickers[0] ?? "AAPL";
  const selectedIsPinned = tickers.includes(activeTicker);

  return (
    <OperatorDetailShell
      title="Watchlist"
      description="Поиск по всей вселенной инструментов. Watchlist — только закреплённые избранные."
      fillViewport
    >
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[minmax(0,360px)_1fr] gap-4 min-h-0 h-full">
        <div className="cockpit-panel flex flex-col min-h-0 overflow-hidden">
          <div className="p-3 border-b border-cockpit-border">
            <UniverseSearchField onPick={setSelected} placeholder="Поиск по всем рынкам…" />
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-2">
            {isLoading && tickers.length === 0 ? (
              <div className="flex justify-center py-8">
                <Spinner size={24} />
              </div>
            ) : (
              tickers.map((ticker, index) => (
                <TickerSparkline
                  key={ticker}
                  ticker={ticker}
                  index={index}
                  isSelected={ticker === activeTicker}
                  onClick={() => setSelected(ticker)}
                />
              ))
            )}
            {!selectedIsPinned && activeTicker && (
              <p className="text-[10px] text-terminal-muted px-1">
                {activeTicker} не в избранном — закрепите из поиска, если нужно.
              </p>
            )}
          </div>
        </div>
        <WatchlistTickerPanel ticker={activeTicker} className="min-h-0 h-full" />
      </div>
    </OperatorDetailShell>
  );
}
