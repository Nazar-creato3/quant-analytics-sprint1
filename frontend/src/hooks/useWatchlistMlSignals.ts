"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { forecastApi, type ForecastMlSignal } from "@/lib/api";
import { useActiveTicker } from "@/contexts/ActiveTickerContext";
import { forecastCoreQueryKey } from "@/hooks/useTickerForecast";
import { mlSignalFromForecast } from "@/lib/ml-forecast-signal";

/**
 * ML column for watchlisted tickers.
 * Batch GET /forecast/signals only — do not stampede full forecast per row.
 * Overlay the active ticker from the same core cache as the Forecast desk.
 */
export function useWatchlistMlSignals(symbols: string[]) {
  const { activeTicker } = useActiveTicker();
  const unique = useMemo(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const raw of symbols) {
      const sym = raw.trim().toUpperCase();
      if (!sym || seen.has(sym)) continue;
      seen.add(sym);
      out.push(sym);
    }
    return out;
  }, [symbols]);

  const batch = useQuery({
    queryKey: ["forecast-signals", unique.join(",")],
    queryFn: () => forecastApi.signals(unique),
    staleTime: 60_000,
    enabled: unique.length > 0,
  });

  const activeCore = useQuery({
    queryKey: forecastCoreQueryKey(activeTicker),
    queryFn: () => forecastApi.get(activeTicker),
    staleTime: 60_000,
    retry: 1,
    enabled: Boolean(activeTicker) && unique.includes(activeTicker.toUpperCase()),
  });

  const bySymbol = useMemo(() => {
    const map = new Map<string, ForecastMlSignal>();
    for (const item of batch.data ?? []) {
      map.set(item.symbol.toUpperCase(), item);
    }
    const fromDesk = mlSignalFromForecast(activeTicker, activeCore.data);
    if (fromDesk) map.set(activeTicker.toUpperCase(), fromDesk);
    return map;
  }, [batch.data, activeCore.data, activeTicker]);

  const pending = batch.isLoading && !activeCore.data;
  return { bySymbol, isLoading: pending && bySymbol.size === 0, isFetching: batch.isFetching };
}
