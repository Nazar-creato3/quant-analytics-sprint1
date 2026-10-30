"use client";

import { useQuery } from "@tanstack/react-query";
import { watchlistApi } from "@/lib/api";
import type { WatchlistEntry } from "@/lib/api";

/** Shared React Query key — invalidate after settings/watchlist changes. */
export const WATCHLIST_QUERY_KEY = ["dashboard-watchlist"] as const;

/** Env-default fallback when API is unavailable (not a display cap). */
export const FALLBACK_WATCHLIST = [
  "SBER", "GAZP", "LKOH", "YDEX", "ROSN", "GMKN", "PLZL", "MOEX", "IMOEX",
  "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "SPY", "QQQ", "JPM", "V", "BTC-USD",
];

export function useEffectiveWatchlist() {
  const query = useQuery({
    queryKey: WATCHLIST_QUERY_KEY,
    queryFn: () => watchlistApi.effective(),
    staleTime: 30_000,
    refetchOnWindowFocus: true,
  });

  const tickers = query.data?.tickers?.length
    ? query.data.tickers
    : FALLBACK_WATCHLIST;

  const entries: WatchlistEntry[] = query.data?.entries ?? [];

  return { ...query, tickers, entries };
}
