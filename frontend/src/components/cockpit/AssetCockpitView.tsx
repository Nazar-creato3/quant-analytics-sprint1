"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useCallback, useState } from "react";
import { AlertTriangle, ArrowLeft, RefreshCw } from "lucide-react";
import { cockpitApi, forecastApi } from "@/lib/api";
import { useCockpitWebSocket } from "@/hooks/useWebSocket";
import { normalizeForecastHierarchy } from "@/lib/forecast-hierarchy";
import { NavBar } from "@/components/layout/NavBar";
import { AssetCockpitHeader } from "./AssetCockpitHeader";
import { AssetCockpitChart } from "./AssetCockpitChart";
import { AssetCockpitNewsTimeline } from "./AssetCockpitNewsTimeline";
import { AssetCockpitEventsBlock } from "./AssetCockpitEventsBlock";
import { AssetCockpitRightPanel } from "./AssetCockpitRightPanel";
import { AssetCockpitWhySoBlock } from "./AssetCockpitWhySoBlock";
import { AssetCockpitPredictionPanel } from "./AssetCockpitPredictionPanel";
import { AssetCockpitEditPosition } from "./AssetCockpitEditPosition";
import { AssetCockpitDealIntentEditor } from "./AssetCockpitDealIntentEditor";
import { NameDeskCard } from "@/components/operator/NameDeskCard";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { extractErrorMessage } from "@/lib/errors";
import { CrossActions } from "@/components/shared/CrossActions";
interface AssetCockpitViewProps {
  symbol: string;
}

export function AssetCockpitView({ symbol }: AssetCockpitViewProps) {
  const queryClient = useQueryClient();
  const normalized = symbol.trim().toUpperCase();
  const [wsLivePrice, setWsLivePrice] = useState<number | null>(null);

  const onWsPrice = useCallback((data: Record<string, unknown>) => {
    const price = data.price ?? data.last ?? data.close;
    if (typeof price === "number") setWsLivePrice(price);
  }, []);

  const { connected: wsConnected } = useCockpitWebSocket(normalized, onWsPrice);

  const refreshCockpit = () => {
    queryClient.invalidateQueries({ queryKey: ["asset-cockpit", normalized] });
    queryClient.invalidateQueries({ queryKey: ["forecast", normalized] });
    queryClient.invalidateQueries({ queryKey: ["cockpit-bars", normalized] });
    queryClient.invalidateQueries({ queryKey: ["cockpit-pending-maneuver", normalized] });
    void refetch();
  };

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["asset-cockpit", normalized],
    queryFn: () => cockpitApi.get(normalized),
    staleTime: 45_000,
    enabled: !!normalized,
    refetchInterval: wsConnected ? false : 5_000,
  });

  const {
    data: forecastData,
    isLoading: forecastLoading,
    error: forecastError,
  } = useQuery({
    queryKey: ["forecast", normalized],
    queryFn: () => forecastApi.get(normalized),
    staleTime: 60_000,
    enabled: !!normalized,
    refetchInterval: wsConnected ? false : 10_000,
  });

  const displayPrice = wsLivePrice ?? data?.price ?? null;

  const predictionView = forecastData ? normalizeForecastHierarchy(forecastData) : null;

  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text flex flex-col operator-shell">
      <NavBar activeTab="dashboard" />
      <div className="border-b border-cockpit-border bg-cockpit-surface px-4 py-2 shrink-0 flex items-center justify-between">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-xs text-qa-muted hover:text-qa-text"
        >
          <ArrowLeft size={12} />
          Карточка бумаги
        </Link>
        <button
          type="button"
          onClick={refreshCockpit}
          disabled={isFetching}
          className="cockpit-action-btn text-qa-muted hover:text-qa-text disabled:opacity-50"
        >
          <RefreshCw size={11} className={isFetching ? "animate-spin" : undefined} />
          Обновить
        </button>
      </div>

      <main className="flex-1 overflow-auto p-3 lg:p-4">
        <div className="space-y-3 max-w-[1600px] mx-auto">
          {isLoading && !data ? (
            <div className="h-24 skeleton rounded-lg" />
          ) : error ? (
            <div className="cockpit-panel p-6 text-center">
              <AlertTriangle size={22} className="mx-auto text-terminal-down mb-2" />
              <p className="text-sm text-terminal-down">
                {extractErrorMessage(error, "Не удалось загрузить данные")}
              </p>
              <button
                type="button"
                onClick={refreshCockpit}
                disabled={isFetching}
                className="mt-4 btn-primary text-xs"
              >
                Повторить
              </button>
            </div>
          ) : !data ? (
            <div className="cockpit-panel p-4 text-center text-sm text-qa-muted">
              Loading {normalized}…
            </div>
          ) : (
            <>
              <AssetCockpitHeader data={data} />
              <CrossActions ticker={normalized} />
            </>
          )}

          <div className="grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-3 items-start">
            <div className="space-y-3 min-w-0">
              <ErrorBoundary>
                <AssetCockpitChart
                  symbol={normalized}
                  priceRange={data?.price_range}
                  volatilityBands={data?.volatility_bands}
                  livePrice={displayPrice}
                  dataSource={data?.quote_source}
                  returnInterval={
                    predictionView
                      ? {
                          p10: predictionView.interval_forecast.p10,
                          p90: predictionView.interval_forecast.p90,
                        }
                      : undefined
                  }
                />
              </ErrorBoundary>
              <ErrorBoundary>
                <div className="cockpit-panel overflow-hidden">
                  <NameDeskCard ticker={normalized} variant="panel" />
                </div>
              </ErrorBoundary>

              {data && (
                <>
                  <ErrorBoundary>
                    {forecastLoading ? (
                      <div className="cockpit-panel p-6 skeleton h-48 rounded-lg" />
                    ) : forecastError || !predictionView ? (
                      <div className="cockpit-panel p-4 text-center text-xs text-qa-muted">
                        Prediction Panel недоступен для {normalized}
                      </div>
                    ) : (
                      <AssetCockpitPredictionPanel
                        view={predictionView}
                        livePrice={displayPrice}
                        symbol={normalized}
                      />
                    )}
                  </ErrorBoundary>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <AssetCockpitNewsTimeline symbol={data.symbol} articles={data.news} />
                    <AssetCockpitEventsBlock events={data.macro_events} />
                  </div>
                </>
              )}
              <ErrorBoundary>
                {data?.intents?.length ? (
                  <AssetCockpitDealIntentEditor symbol={normalized} intentSummaries={data.intents} />
                ) : null}
                <AssetCockpitEditPosition symbol={normalized} />
              </ErrorBoundary>
              {data?.why_so && <AssetCockpitWhySoBlock whySo={data.why_so} />}
            </div>
            {data ? (
              <ErrorBoundary>
                <AssetCockpitRightPanel
                  data={data}
                  predictionView={predictionView}
                  className="xl:sticky xl:top-3"
                />
              </ErrorBoundary>
            ) : (
              <div className="cockpit-panel p-4 skeleton h-64 hidden xl:block" />
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
