"use client";

import { useQuery } from "@tanstack/react-query";
import { marketApi } from "@/lib/api";
import type { OHLCVBar } from "@/types";

export function useChartIndicators(
  ticker: string,
  bars: OHLCVBar[],
  timeframe: string,
  enabled: boolean,
) {
  const last = bars[bars.length - 1];
  return useQuery({
    queryKey: [
      "chart-indicators",
      ticker,
      timeframe,
      bars.length,
      last?.timestamp,
      last?.close,
    ],
    queryFn: () => marketApi.computeIndicators({ ticker, timeframe, bars }),
    enabled: enabled && bars.length > 0 && Boolean(ticker),
    staleTime: 30_000,
  });
}
