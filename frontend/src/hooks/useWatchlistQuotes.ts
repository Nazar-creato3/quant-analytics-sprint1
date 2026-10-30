"use client";

import { useEffect, useMemo, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { marketApi } from "@/lib/api";
import { useMobilePollingInterval } from "./useIsMobile";

export interface WatchlistQuote {
  symbol: string;
  price: number | null;
  changePct: number | null;
  volume: number | null;
  freshnessLabel: string;
  licenseTag: string | null;
}

function parseQuote(symbol: string, raw: Record<string, unknown>): WatchlistQuote {
  const allowed = raw.display_allowed !== false;
  const priceRaw = allowed ? raw.last ?? raw.price ?? raw.close : null;
  const changeRaw =
    raw.change_pct ?? raw.change_percent ?? raw.changePercent ?? raw.percent_change;
  const volumeRaw = raw.volume ?? raw.volume_24h;

  const price =
    priceRaw != null && Number.isFinite(Number(priceRaw)) ? Number(priceRaw) : null;
  const changePct =
    changeRaw != null && Number.isFinite(Number(changeRaw)) ? Number(changeRaw) : null;
  const volume =
    volumeRaw != null && Number.isFinite(Number(volumeRaw)) ? Number(volumeRaw) : null;

  return {
    symbol,
    price,
    changePct,
    volume,
    freshnessLabel: typeof raw.freshness_label === "string" && raw.freshness_label.trim()
      ? raw.freshness_label
      : "нет данных",
    licenseTag: typeof raw.license_tag === "string" ? raw.license_tag : null,
  };
}

/** Live quotes for watchlist tickers — staggered fan-out, no heavy enrichment. */
export function useWatchlistQuotes(tickers: string[], limit = 12) {
  const pollInterval = useMobilePollingInterval(15_000, 60_000);
  const symbols = useMemo(
    () => tickers.slice(0, limit).map((s) => s.toUpperCase()),
    [tickers, limit],
  );
  const [enabledCount, setEnabledCount] = useState(Math.min(4, symbols.length));

  useEffect(() => {
    setEnabledCount(Math.min(4, symbols.length));
    if (symbols.length <= 4) return;
    const id = window.setInterval(() => {
      setEnabledCount((n) => {
        if (n >= symbols.length) {
          window.clearInterval(id);
          return n;
        }
        return Math.min(symbols.length, n + 4);
      });
    }, 250);
    return () => window.clearInterval(id);
  }, [symbols]);

  const queries = useQueries({
    queries: symbols.map((symbol, index) => ({
      queryKey: ["watchlist-quote", symbol],
      queryFn: () => marketApi.getQuote(symbol),
      staleTime: pollInterval / 2,
      refetchInterval: pollInterval,
      enabled: Boolean(symbol) && index < enabledCount,
      retry: 1,
    })),
  });

  const bySymbol = new Map<string, WatchlistQuote>();
  symbols.forEach((symbol, index) => {
    const data = queries[index]?.data;
    bySymbol.set(
      symbol,
      data ? parseQuote(symbol, data) : { symbol, price: null, changePct: null, volume: null, freshnessLabel: "нет данных", licenseTag: null },
    );
  });

  const isLoading = queries.some((query) => query.isLoading && !query.data);
  const isFetching = queries.some((query) => query.isFetching);

  return { bySymbol, isLoading, isFetching };
}
