"use client";

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { forecastApi, FORECAST_NARRATIVE_MESSAGE_RU } from "@/lib/api";
import type { ForecastData } from "@/types";
import { normalizeForecastHierarchy } from "@/lib/forecast-hierarchy";

export function forecastCoreQueryKey(symbol: string) {
  return ["forecast", symbol, "core"] as const;
}

export function useTickerForecast(symbol: string) {
  const queryClient = useQueryClient();

  const core = useQuery<ForecastData>({
    queryKey: forecastCoreQueryKey(symbol),
    queryFn: () => forecastApi.get(symbol),
    staleTime: 60_000,
    enabled: !!symbol,
    retry: (failureCount, err) => {
      const code = (err as { code?: string })?.code;
      if (code === "ECONNABORTED") return false;
      if (failureCount >= 2) return false;
      const status = (err as { response?: { status?: number } })?.response?.status;
      return status === 503 || status === 502 || status === 504;
    },
    retryDelay: (attempt) => Math.min(1500 * 2 ** attempt, 12_000),
  });

  const upgrades = useQuery({
    queryKey: ["forecast", symbol, "upgrades"],
    queryFn: () => forecastApi.getUpgradeLayers(symbol),
    staleTime: 120_000,
    enabled: !!symbol && !!core.data,
    retry: 1,
  });

  // Free template text loads by itself; the paid AI text only after an explicit click.
  const [aiRequested, setAiRequested] = useState(false);
  const narrative = useQuery({
    queryKey: ["forecast", symbol, "narrative", aiRequested ? "ai" : "template"],
    queryFn: () => forecastApi.getNarrative(symbol, aiRequested),
    staleTime: 120_000,
    enabled: !!symbol && !!core.data,
    retry: 1,
  });

  const data = useMemo((): ForecastData | undefined => {
    if (!core.data) return undefined;
    let merged: ForecastData = { ...core.data };
    if (upgrades.data) {
      merged = {
        ...merged,
        ensemble_forecast: upgrades.data.ensemble_forecast ?? merged.ensemble_forecast,
        conformal_intervals: upgrades.data.conformal_intervals ?? merged.conformal_intervals,
        bull_base_bear: upgrades.data.bull_base_bear ?? merged.bull_base_bear,
        global_macro: upgrades.data.global_macro ?? merged.global_macro,
        track_record_chart: upgrades.data.track_record_chart ?? merged.track_record_chart,
        live_direction_accuracy:
          upgrades.data.live_direction_accuracy ?? merged.live_direction_accuracy,
        market_beat: upgrades.data.market_beat ?? merged.market_beat,
      };
    }
    if (!narrative.data?.scenario_disclosure) return merged;
    return {
      ...merged,
      llm_narrative: narrative.data.llm_narrative ?? merged.llm_narrative,
      scenario_disclosure: narrative.data.scenario_disclosure,
      structured: merged.structured
        ? {
            ...merged.structured,
            actionable_summary: narrative.data.actionable_summary?.length
              ? narrative.data.actionable_summary
              : merged.structured.actionable_summary,
          }
        : merged.structured,
    };
  }, [core.data, upgrades.data, narrative.data]);

  const hierarchyView = useMemo(() => (data ? normalizeForecastHierarchy(data) : null), [data]);

  const refetchAll = () => {
    queryClient.invalidateQueries({ queryKey: ["forecast", symbol] });
    void core.refetch();
    void upgrades.refetch();
    void narrative.refetch();
  };

  return {
    data,
    hierarchyView,
    isLoading: core.isLoading && !core.data,
    isFetching: core.isFetching,
    error: core.error,
    dataUpdatedAt: core.dataUpdatedAt,
    narrativeLoading: narrative.isLoading,
    narrativeError: narrative.error,
    narrativeMessage: FORECAST_NARRATIVE_MESSAGE_RU,
    refetchNarrative: narrative.refetch,
    aiRequested,
    requestAiExplanation: () => setAiRequested(true),
    refetchAll,
    refetchUpgrades: upgrades.refetch,
  };
}

