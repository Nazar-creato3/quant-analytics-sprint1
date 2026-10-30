"use client";

import { useMemo } from "react";
import { useActiveTicker } from "@/contexts/ActiveTickerContext";
import { useQuery } from "@tanstack/react-query";
import { useHealth } from "@/hooks";
import { useLocale } from "@/contexts/LocaleContext";
import { useMountPhase } from "@/hooks/useMountPhase";
import { maneuversApi } from "@/lib/api";
import { OPEN_POSITION_STATUS_FILTER } from "@/lib/maneuvers";
import { AlertTriangle } from "lucide-react";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { BrainNow } from "./BrainNow";
import { ControlBar } from "./ControlBar";
import { WatchlistSidebar } from "./WatchlistSidebar";
import { MainChartPanel } from "./MainChartPanel";
import { DecisionFeed } from "./DecisionFeed";
import { BottomStrip } from "./BottomStrip";
import { NEWS_DISPLAY_COUNT } from "@/constants/news";
import { NewsPanel } from "./NewsPanel";
import { MobileDashboardStack } from "@/components/mobile/MobileDashboardStack";
import { MobileWatchlistSection } from "@/components/mobile/MobileWatchlistSection";
import { MobilePositionsPreview } from "@/components/mobile/MobilePositionsPreview";
import { useMobilePollingInterval } from "@/hooks/useIsMobile";
import { HOME_USER_COPY } from "@/app/homeUserCopy";
import { resolveHomeTicker } from "@/lib/homeTicker";

export function OperatorDashboard() {
  const { activeTicker, setActiveTicker } = useActiveTicker();
  const { t } = useLocale();
  const { data: health } = useHealth();
  const isLive = health?.trading_mode === "live";

  const pollInterval = useMobilePollingInterval(15_000, 75_000);

  const { data: openPositions } = useQuery({
    queryKey: ["operator-open-positions"],
    queryFn: () => maneuversApi.list({ status: OPEN_POSITION_STATUS_FILTER, page_size: 50 }),
    refetchInterval: pollInterval,
  });

  const largestPosition = useMemo(() => {
    const items = openPositions?.items ?? [];
    if (items.length === 0) return null;
    return items.reduce((max, m) =>
      (m.position_size_usd ?? 0) > (max.position_size_usd ?? 0) ? m : max,
    );
  }, [openPositions]);

  const selectedTicker = resolveHomeTicker(activeTicker, largestPosition?.ticker);
  const chartPosition =
    largestPosition && largestPosition.ticker === selectedTicker ? largestPosition : null;

  const chartReady = useMountPhase(1, 150);
  const feedReady = useMountPhase(2, 350);
  const newsReady = useMountPhase(3, 500);
  const bottomReady = useMountPhase(4, 700);

  return (
    <div className="flex-1 flex flex-col overflow-y-auto md:overflow-hidden min-h-0">
      {isLive && (
        <div className="alert-error border-b px-4 py-1.5 flex items-center gap-2 text-xs shrink-0">
          <AlertTriangle size={12} className="text-terminal-down shrink-0" />
          <span className="font-bold">{HOME_USER_COPY.liveBanner}</span>
          <span className="text-terminal-down/80">— {t("live.banner")}</span>
        </div>
      )}

      <ControlBar />
      <BrainNow />

      <MobileDashboardStack
        watchlist={
          <MobileWatchlistSection
            selectedTicker={selectedTicker}
            onSelectTicker={setActiveTicker}
          />
        }
        maneuvers={
          feedReady ? (
            <DecisionFeed enabled className="!border-0 !bg-transparent min-h-[200px] max-h-[420px]" />
          ) : (
            <div className="min-h-[120px] animate-pulse bg-cockpit-panel rounded-lg" />
          )
        }
        positions={bottomReady ? <MobilePositionsPreview /> : null}
        chart={
          chartReady ? (
            <MainChartPanel
              ticker={selectedTicker}
              position={chartPosition}
              fixedHeight={360}
              className="!border-0 !bg-transparent"
            />
          ) : (
            <div className="min-h-[360px] animate-pulse bg-cockpit-panel rounded-lg" />
          )
        }
        news={
          newsReady ? (
            <NewsPanel compact maxItems={NEWS_DISPLAY_COUNT} enabled className="min-h-[120px] !border-0 !bg-transparent" />
          ) : null
        }
        secondary={null}
      />

      <div
        className="hidden md:flex flex-1 overflow-hidden min-h-0"
        data-tour="dashboard-desk"
      >
        <ErrorBoundary>
          <WatchlistSidebar
            selectedTicker={selectedTicker}
            onSelectTicker={setActiveTicker}
          />
        </ErrorBoundary>

        <div className="flex-1 flex flex-col xl:flex-row min-w-0 min-h-0 overflow-y-auto xl:overflow-hidden p-2 gap-2">
          {/* Chart — largest column */}
          <ErrorBoundary>
            {chartReady ? (
              <MainChartPanel
                ticker={selectedTicker}
                position={chartPosition}
                className="w-full xl:flex-[2.15] min-w-0 shrink min-h-[560px] xl:min-h-0 h-auto xl:h-auto overflow-hidden"
              />
            ) : (
              <div className="cockpit-panel w-full xl:flex-[2.15] min-h-[420px] xl:min-h-0 h-[480px] xl:h-auto animate-pulse bg-cockpit-panel" />
            )}
          </ErrorBoundary>

          {/* Maneuvers — single panel (approvals live inside Investment Maneuvers) */}
          <div className="flex-1 flex flex-col min-w-0 min-h-0 gap-2 xl:flex-[1.1] overflow-hidden">
            <ErrorBoundary>
              {feedReady ? (
                <DecisionFeed
                  enabled
                  className="flex-1 min-h-[200px] xl:min-h-0"
                />
              ) : null}
            </ErrorBoundary>
          </div>

          {/* News — compact */}
          <ErrorBoundary>
            {newsReady ? (
              <NewsPanel
                compact
                maxItems={NEWS_DISPLAY_COUNT}
                enabled
                className="w-full xl:w-56 shrink-0 max-h-[360px] xl:max-h-none xl:h-auto min-h-0"
              />
            ) : null}
          </ErrorBoundary>
        </div>
      </div>

      <ErrorBoundary>
        {bottomReady ? (
          <div className="hidden md:block shrink-0">
            <BottomStrip enabled resizable defaultHeight={210} />
          </div>
        ) : null}
      </ErrorBoundary>
    </div>
  );
}
