"use client";

import { useEffect, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { RefreshCw } from "lucide-react";
import { marketApi } from "@/lib/api";
import { BARS_POLL_MS, QUOTE_POLL_MS } from "@/lib/marketPoll";
import type { OHLCVBar } from "@/types";
import { Skeleton } from "@/components/ui";
import { generateMockBars } from "./ohlcvAdapters";
import { LightweightChart } from "./LightweightChart";

export interface LightweightChartLoaderProps {
  ticker: string;
  timeframe?: "1d" | "1h" | "4h" | "15m" | "5m" | "1w";
  height?: number;
  showVolume?: boolean;
  className?: string;
  /** Use synthetic bars when API is unavailable (default: false — never fake live prices). */
  allowMockFallback?: boolean;
  limit?: number;
}

export function LightweightChartLoader({
  ticker,
  timeframe = "1d",
  height = 280,
  showVolume = true,
  className,
  allowMockFallback = false,
  limit = 120,
}: LightweightChartLoaderProps) {
  const quoteForceRef = useRef(true);
  const barsForceRef = useRef(true);

  useEffect(() => {
    quoteForceRef.current = true;
    barsForceRef.current = true;
  }, [ticker]);

  const { data, isLoading, error, refetch } = useQuery<OHLCVBar[]>({
    queryKey: ["bars", ticker, timeframe, "lightweight-loader", limit],
    queryFn: () => {
      const force = barsForceRef.current;
      barsForceRef.current = false;
      return marketApi.getBars(ticker, timeframe, limit, { forceRefresh: force });
    },
    staleTime: BARS_POLL_MS,
    refetchInterval: BARS_POLL_MS,
    refetchIntervalInBackground: true,
    enabled: !!ticker,
    retry: 1,
  });

  const { data: quote } = useQuery({
    queryKey: ["quote", ticker, "lightweight-loader"],
    queryFn: () => {
      const force = quoteForceRef.current;
      quoteForceRef.current = false;
      return marketApi.getQuote(ticker, { forceRefresh: force });
    },
    staleTime: QUOTE_POLL_MS,
    refetchInterval: QUOTE_POLL_MS,
    refetchIntervalInBackground: true,
    enabled: !!ticker,
    retry: 1,
  });

  const livePrice = typeof quote?.price === "number" ? quote.price : null;

  const { bars, isMockData } = useMemo(() => {
    if (data?.length) return { bars: data, isMockData: false };
    if (allowMockFallback && ticker) {
      return { bars: generateMockBars(ticker, limit), isMockData: true };
    }
    return { bars: undefined, isMockData: false };
  }, [data, allowMockFallback, ticker, limit]);

  if (isLoading && !bars?.length) {
    return (
      <div className={clsx("space-y-2", className)}>
        <Skeleton className="h-6 w-32" />
        <div className="skeleton rounded-lg" style={{ height }} />
      </div>
    );
  }

  if (!bars?.length) {
    return (
      <div
        className={clsx(
          "flex flex-col items-center justify-center border border-dashed border-qa-border rounded-lg text-qa-muted text-xs gap-2",
          className,
        )}
        style={{ height }}
      >
        <span>Нет данных для {ticker}</span>
        {error && (
          <span className="text-qa-muted text-[10px] max-w-xs text-center">
            API market/bars недоступен
          </span>
        )}
        <button type="button" onClick={() => refetch()} className="btn-ghost py-1 text-xs">
          <RefreshCw size={11} /> Обновить
        </button>
      </div>
    );
  }

  return (
    <LightweightChart
      ticker={ticker}
      bars={bars}
      timeframe={timeframe}
      height={height}
      showVolume={showVolume}
      className={className}
      isMockData={isMockData}
      livePrice={livePrice}
    />
  );
}
