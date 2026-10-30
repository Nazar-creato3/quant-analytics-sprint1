"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { pipelineApi } from "@/lib/api";
import { ManeuverReport } from "@/types";
import { ManeuversTable } from "@/components/maneuvers/ManeuversTable";
import { ReportCard, SystemStatus } from "@/components/dashboard/ReportCard";
import { PortfolioStats, OpenPositions } from "@/components/dashboard/PortfolioStats";
import { LightweightChartLoader } from "@/components/charts/LightweightChartLoader";
import { TickerSparkline } from "@/components/charts/PriceChart";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { formatPipelineManeuverToast } from "@/lib/maneuvers";
import { useHealth, usePipelineRun, useEffectiveWatchlist } from "@/hooks";
import { toast } from "react-hot-toast";
import { UniverseSearchField } from "@/components/search/UniverseSearchField";
import { Play, RefreshCw, AlertTriangle, ChevronRight } from "lucide-react";

export function ResearchDashboard() {
  const queryClient = useQueryClient();
  const { tickers: watchlist } = useEffectiveWatchlist();
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [selectedTicker, setSelectedTicker] = useState("SPY");
  const [showAllReports, setShowAllReports] = useState(false);

  const { data: health } = useHealth();

  const { data: reportsPage, isLoading: reportsLoading } = useQuery({
    queryKey: ["reports"],
    queryFn: () => pipelineApi.listReports(1, 20),
  });

  const reports = reportsPage?.items ?? [];
  const activeReportId = selectedReportId || reports[0]?.id;

  const { data: activeReport, isLoading: reportLoading } = useQuery<ManeuverReport>({
    queryKey: ["report", activeReportId],
    queryFn: () => pipelineApi.getReport(activeReportId!),
    enabled: !!activeReportId,
  });

  const { trigger, isRunning, status: pipelineStatus } = usePipelineRun({
    onComplete: (reportId, stats) => {
      setSelectedReportId(reportId);
      queryClient.invalidateQueries({ queryKey: ["reports"] });
      toast.success(
        formatPipelineManeuverToast(
          stats?.tradeable_count,
          stats?.maneuver_slots,
          stats?.pending_approval_count,
          stats?.backfill_hint,
        ),
      );
    },
    onError: (msg) => toast.error(`Pipeline: ${msg}`),
  });

  const isLive = health?.trading_mode === "live";
  const visibleReports = showAllReports ? reports : reports.slice(0, 5);

  return (
    <>
      {isLive && (
        <div className="alert-error border-b px-6 py-2 flex items-center gap-2 text-sm">
          <AlertTriangle size={14} className="text-terminal-down shrink-0" />
          <span className="font-semibold">LIVE TRADING ACTIVE</span>
          <span className="text-terminal-down/70 ml-2">
            — Реальные деньги под риском. Проверяйте каждый маневр перед одобрением.
          </span>
        </div>
      )}

      <div className="flex-1 flex overflow-hidden">
        <aside className="w-64 cockpit-sidebar flex flex-col overflow-hidden shrink-0">
          <div className="p-3 border-b border-cockpit-border">
            <div className="section-title mb-2">Инструменты</div>
            <UniverseSearchField
              compact
              placeholder="Тикер или название компании…"
              onPick={setSelectedTicker}
            />
            <p className="text-[8px] text-qa-muted mt-1 mb-2">Избранное ниже</p>
            <div className="space-y-1 max-h-72 overflow-y-auto pr-0.5">
              {watchlist.map((t, index) => (
                <TickerSparkline
                  key={t}
                  ticker={t}
                  index={index}
                  onClick={() => setSelectedTicker(t)}
                  isSelected={t === selectedTicker}
                />
              ))}
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="section-title">История</span>
              <SystemStatus health={health} />
            </div>

            <button
              onClick={() => trigger(undefined)}
              disabled={isRunning}
              className="btn-primary w-full justify-center mb-3 text-xs py-2"
            >
              {isRunning ? (
                <><RefreshCw size={12} className="animate-spin" /> {pipelineStatus}…</>
              ) : (
                <><Play size={12} /> Запустить Pipeline</>
              )}
            </button>

            <div className="space-y-1.5">
              {reportsLoading
                ? Array.from({ length: 3 }).map((_, i) => (
                    <div key={i} className="skeleton h-16 rounded-lg" />
                  ))
                : visibleReports.map(r => (
                    <ReportCard
                      key={r.id}
                      report={r}
                      isSelected={r.id === activeReportId}
                      onClick={() => setSelectedReportId(r.id)}
                    />
                  ))}

              {reports.length > 5 && !showAllReports && (
                <button
                  onClick={() => setShowAllReports(true)}
                  className="btn-ghost w-full text-xs justify-center py-1.5"
                >
                  Показать все ({reports.length})
                  <ChevronRight size={12} />
                </button>
              )}

              {reports.length === 0 && !reportsLoading && (
                <p className="text-xs text-qa-muted text-center py-6">
                  Нет отчётов.<br />Запустите Pipeline.
                </p>
              )}
            </div>
          </div>
        </aside>

        <main className="flex-1 overflow-y-auto">
          <div className="p-6 space-y-6">
            <ErrorBoundary>
              <PortfolioStats />
            </ErrorBoundary>

            <div className="grid grid-cols-12 gap-6">
              <div className="col-span-4 card p-4">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-sm font-semibold text-white">{selectedTicker}</span>
                  <span className="section-title">1D</span>
                </div>
                <ErrorBoundary>
                  <LightweightChartLoader
                    ticker={selectedTicker}
                    timeframe="1d"
                    height={280}
                    showVolume
                    allowMockFallback={false}
                  />
                </ErrorBoundary>
              </div>

              <div className="col-span-8">
                <ErrorBoundary>
                  {reportLoading ? (
                    <div className="card p-5 space-y-3">
                      {Array.from({ length: 6 }).map((_, i) => (
                        <div key={i} className="skeleton h-9 rounded" />
                      ))}
                    </div>
                  ) : activeReport ? (
                    <ManeuversTable report={activeReport} />
                  ) : (
                    <div className="flex flex-col items-center justify-center h-72 border border-dashed border-qa-border rounded-xl text-qa-muted gap-3">
                      <Play size={32} className="opacity-20" />
                      <p className="text-sm">Запустите pipeline для получения 10 маневров</p>
                    </div>
                  )}
                </ErrorBoundary>
              </div>
            </div>

            <ErrorBoundary>
              <OpenPositions />
            </ErrorBoundary>
          </div>
        </main>
      </div>
    </>
  );
}
