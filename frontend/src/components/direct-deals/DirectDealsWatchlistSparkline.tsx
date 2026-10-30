"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { marketApi } from "@/lib/api";
import { CHART_COLORS } from "@/lib/chartColors";

interface DirectDealsWatchlistSparklineProps {
  ticker: string;
  index?: number;
  priority?: boolean;
  width?: number;
  height?: number;
}

export function DirectDealsWatchlistSparkline({
  ticker,
  index = 0,
  priority = false,
  width = 48,
  height = 16,
}: DirectDealsWatchlistSparklineProps) {
  const [fetchEnabled, setFetchEnabled] = useState(priority);

  useEffect(() => {
    if (priority) {
      setFetchEnabled(true);
      return;
    }
    const timer = setTimeout(() => setFetchEnabled(true), index * 350);
    return () => clearTimeout(timer);
  }, [priority, index, ticker]);

  const { data: bars } = useQuery({
    queryKey: ["watchlist-sparkline", ticker],
    queryFn: () => marketApi.getBars(ticker, "1d", 20),
    staleTime: 120_000,
    enabled: fetchEnabled,
    retry: 1,
  });

  const points = useMemo(() => {
    if (!bars?.length || bars.length < 2) return null;
    const values = bars.map((bar) => bar.close);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    const pad = 1;
    return values
      .map((value, i) => {
        const x = pad + (i / (values.length - 1)) * (width - pad * 2);
        const y = pad + (1 - (value - min) / range) * (height - pad * 2);
        return `${x},${y}`;
      })
      .join(" ");
  }, [bars, width, height]);

  if (!fetchEnabled || !points) {
    return <div className="w-12 h-4 rounded bg-qa-bg/40 shrink-0" aria-hidden />;
  }

  const first = bars![0].close;
  const last = bars![bars!.length - 1].close;
  const positive = last >= first;
  const color = positive ? CHART_COLORS.success : CHART_COLORS.danger;

  return (
    <svg
      width={width}
      height={height}
      className="shrink-0 overflow-visible"
      aria-hidden
    >
      <polyline
        fill="none"
        stroke={color}
        strokeWidth={1.2}
        strokeLinejoin="round"
        strokeLinecap="round"
        points={points}
      />
    </svg>
  );
}
