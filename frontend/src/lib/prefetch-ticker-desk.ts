import type { QueryClient } from "@tanstack/react-query";
import { forecastApi, marketApi } from "@/lib/api";
import { forecastCoreQueryKey } from "@/hooks/useTickerForecast";
import { terminalApi } from "@/lib/terminal-api";

/** Warm Chart + Forecast + Fundamentals before Terminal mounts. */
export async function prefetchTickerDesk(queryClient: QueryClient, symbol: string): Promise<void> {
  const ticker = symbol.trim().toUpperCase();
  if (!ticker) return;
  await Promise.allSettled([
    queryClient.prefetchQuery({
      queryKey: forecastCoreQueryKey(ticker),
      queryFn: () => forecastApi.get(ticker),
      staleTime: 60_000,
    }),
    queryClient.prefetchQuery({
      queryKey: ["fundamentals-snapshot", ticker],
      queryFn: () => marketApi.fundamentalsSnapshot(ticker),
      staleTime: 120_000,
    }),
    queryClient.prefetchQuery({
      queryKey: ["terminal", "chart", ticker],
      queryFn: () => terminalApi.fetchChart(ticker),
      staleTime: 30_000,
    }),
  ]);
}
