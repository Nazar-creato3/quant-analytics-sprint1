"use client";

import { useCallback, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { portfolioApi } from "@/lib/api";
import { extractErrorMessage } from "@/lib/errors";
import { formatUsd } from "@/lib/format";
import { usePortfolioMetricsWebSocket } from "@/hooks/useWebSocket";
import { useUserQueryScope } from "@/hooks/useUserQueryScope";
import { usePathname } from "next/navigation";
import { useDocumentVisibility } from "@/hooks/useDocumentVisibility";
import { clsx } from "clsx";
import { Loader2 } from "lucide-react";
import { toast } from "react-hot-toast";
import type { PortfolioMetrics } from "@/types";
import { LiveDataBadge } from "@/components/shared/LiveDataBadge";
import { useDataFreshness } from "@/hooks/useLiveFreshness";
import { LlmStatusIndicator } from "@/components/layout/LlmStatusIndicator";
import { AdminOnlyNotice } from "@/components/shared/AdminOnlyNotice";
import { criticalBanner } from "@/lib/notifications";
import { useProductContext } from "@/contexts/ProductContext";

interface MetricItemProps {
  label: string;
  labelShort: string;
  value: string;
  accent?: boolean;
  stale?: boolean;
  loading?: boolean;
  title?: string;
}

function MetricItem({ label, labelShort, value, accent, stale, loading, title }: MetricItemProps) {
  return (
    <div
      className="flex flex-col items-end leading-none min-w-[2.5rem]"
      title={title ?? label}
      data-stale={stale ? "true" : "false"}
    >
      <span className="hidden sm:inline text-[11px] uppercase tracking-wider text-qa-text mb-0.5">
        {label}
      </span>
      <span className="sm:hidden text-[11px] uppercase tracking-wider text-qa-text mb-0.5">
        {labelShort}
      </span>
      {loading ? (
        <Loader2 size={11} className="animate-spin text-qa-muted" aria-hidden />
      ) : (
        <span
          className={clsx(
            "font-mono text-[11px] tabular-nums",
            accent ? "text-terminal-up" : "text-qa-text",
          )}
        >
          {value}
        </span>
      )}
    </div>
  );
}

function venueLabel(name: string): string {
  const lower = name.toLowerCase();
  if (lower.includes("binance")) return "Binance";
  if (lower.includes("finam")) return "Finam";
  if (lower.includes("tinkoff") || lower.includes("t-bank") || lower === "tinkoff") {
    return "Tinkoff";
  }
  return name.charAt(0).toUpperCase() + name.slice(1);
}

function liveAccountTotal(
  metrics: PortfolioMetrics | undefined,
  venueTotalBalance?: number,
): number | null {
  const isPaper = metrics?.mode === "paper";
  if (isPaper) {
    if (metrics?.total_usd != null && Number.isFinite(metrics.total_usd)) {
      return metrics.total_usd;
    }
    return null;
  }
  if (
    metrics?.account_total_usd != null &&
    Number.isFinite(metrics.account_total_usd) &&
    metrics.account_total_usd > 0
  ) {
    return metrics.account_total_usd;
  }
  if (venueTotalBalance != null && Number.isFinite(venueTotalBalance) && venueTotalBalance > 0) {
    return venueTotalBalance;
  }
  if (metrics?.total_usd != null && Number.isFinite(metrics.total_usd)) {
    return metrics.total_usd;
  }
  return null;
}

/** Never let a sparse poll/WS tick wipe paper ledger totals or live venue balances. */
function mergePortfolioMetrics(
  prev: PortfolioMetrics | undefined,
  next: PortfolioMetrics,
): PortfolioMetrics {
  if (!prev) return next;
  // A switch between «Учебный» and «Боевой», or a broker answer, is never a "sparse tick":
  // an empty real account must show 0, not the previous demo 10 000.
  const source = String(next.source ?? "");
  if (prev.mode !== next.mode || source.startsWith("broker") || source === "no_live_broker") return next;

  const merged: PortfolioMetrics = {
    ...next,
    portfolio_allocation_usd: next.portfolio_allocation_usd ?? prev.portfolio_allocation_usd,
    account_balance_usd: next.account_balance_usd ?? prev.account_balance_usd,
    account_total_usd: next.account_total_usd ?? prev.account_total_usd,
  };

  const prevTotal = prev.total_usd;
  const nextTotal = next.total_usd;
  const prevTrading = prev.trading_usd ?? 0;
  const nextTrading = next.trading_usd ?? 0;
  const wipedOpenBook =
    prevTrading > 0.01 &&
    nextTrading === 0 &&
    (next.open_maneuvers == null || next.open_maneuvers === 0) &&
    (prev.open_maneuvers ?? 0) > 0;
  const sparse =
    wipedOpenBook ||
    (prevTotal != null &&
      Number.isFinite(prevTotal) &&
      prevTotal > 0.01 &&
      (nextTotal == null || !Number.isFinite(nextTotal) || nextTotal === 0));

  if (sparse) {
    merged.total_usd = prevTotal;
    merged.balance_usd = prev.balance_usd ?? next.balance_usd;
    merged.trading_usd = prev.trading_usd ?? next.trading_usd;
    merged.open_maneuvers = prev.open_maneuvers ?? next.open_maneuvers;
    merged.deployed_notional_usd = prev.deployed_notional_usd ?? next.deployed_notional_usd;
  }
  return merged;
}

export function NavBarMetrics() {
  const pathname = usePathname();
  const [mounted, setMounted] = useState(false);
  const [wsMetricsAt, setWsMetricsAt] = useState<number | null>(null);
  const queryClient = useQueryClient();
  const { scopedKey, userKey } = useUserQueryScope();
  // Header switch: each book has its own cache entry, so demo totals never leak into «Боевой».
  const { mode } = useProductContext();
  const metricsKey = [...scopedKey("portfolio-metrics"), mode] as const;
  const isDashboard = pathname === "/";
  const isOperator = isDashboard;

  useEffect(() => setMounted(true), []);

  const tabVisible = useDocumentVisibility();
  const pollMs = isOperator ? 30_000 : 60_000;

  const { data, isLoading, isError, isFetching, dataUpdatedAt } = useQuery({
    queryKey: metricsKey,
    queryFn: portfolioApi.metrics,
    enabled: mounted,
    refetchInterval: tabVisible ? pollMs : false,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    staleTime: pollMs,
    retry: 1,
    placeholderData: (prev) => prev,
    structuralSharing: (oldData, newData) =>
      mergePortfolioMetrics(oldData as PortfolioMetrics | undefined, newData as PortfolioMetrics),
  });

  const metricsLastUpdateAt =
    wsMetricsAt != null || dataUpdatedAt > 0
      ? Math.max(dataUpdatedAt > 0 ? dataUpdatedAt : 0, wsMetricsAt ?? 0)
      : null;
  const metricsFreshness = useDataFreshness(metricsLastUpdateAt);

  const onLiveMetrics = useCallback(
    (metrics: PortfolioMetrics) => {
      // The socket pushes the demo ledger; in «Боевой» the broker numbers come from the poll only.
      if (mode === "live" || metrics.mode !== "paper") return;
      setWsMetricsAt(Date.now());
      queryClient.setQueryData(metricsKey, (prev: PortfolioMetrics | undefined) =>
        mergePortfolioMetrics(prev, metrics),
      );
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [queryClient, mode, userKey],
  );

  usePortfolioMetricsWebSocket(mounted, onLiveMetrics, userKey);

  const { data: venueData } = useQuery({
    queryKey: scopedKey("portfolio-venue-balances"),
    queryFn: portfolioApi.balances,
    enabled: mounted,
    refetchInterval: tabVisible ? Math.max(pollMs * 2, 60_000) : false,
    staleTime: pollMs,
    retry: 0,
    placeholderData: (prev) => prev,
  });

  const refreshMutation = useMutation({
    mutationFn: portfolioApi.refresh,
    onSuccess: (result) => {
      if (mode === "live") {
        // The refresh endpoint recalculates the demo book; in «Боевой» just re-read the broker.
        void queryClient.invalidateQueries({ queryKey: metricsKey });
      } else {
        queryClient.setQueryData(metricsKey, (prev: PortfolioMetrics | undefined) =>
          mergePortfolioMetrics(prev, result),
        );
      }
      queryClient.invalidateQueries({ queryKey: scopedKey("portfolio-risk-status") });
      queryClient.invalidateQueries({ queryKey: scopedKey("portfolio-venue-balances") });

      if (result.released_capital_usd > 0) {
        toast.success(
          `Баланс обновлён: освобождено ${formatUsd(result.released_capital_usd, { compact: false })}`,
          { duration: 5000 },
        );
      } else {
        toast.success("Метрики портфеля обновлены", { duration: 3500 });
      }
    },
    onError: (err) => toast.error(extractErrorMessage(err, "Не удалось обновить баланс")),
  });

  const dash = "—";
  const stale = metricsFreshness.state !== "live" || (isFetching && !isLoading);
  const pnlTitle =
    data != null
      ? `uP&L ${formatUsd(data.unrealized_pnl_usd ?? 0, { compact: false })} · rP&L ${formatUsd(data.realized_pnl_usd ?? 0, { compact: false })} · as_of ${data.as_of ?? "—"}`
      : undefined;

  const allocationUsd = data?.portfolio_allocation_usd;
  const accountTotal = liveAccountTotal(data, venueData?.total_balance_usd ?? venueData?.total_usd);

  const cap =
    isLoading || isError
      ? dash
      : allocationUsd != null
        ? formatUsd(allocationUsd, { compact: false })
        : dash;
  const balance =
    isLoading || isError
      ? dash
      : accountTotal != null
        ? formatUsd(accountTotal)
        : dash;
  const trading = isLoading ? dash : isError ? dash : formatUsd(data?.trading_usd);
  const refreshing = refreshMutation.isPending;

  const venues =
    venueData?.venues?.length
      ? venueData.venues
      : data?.venue_balances ?? [];
  const hasVenues = venues.length > 0;

  const handleRefresh = () => {
    if (refreshMutation.isPending || isLoading) return;
    refreshMutation.mutate();
  };

  const handleRefreshKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      handleRefresh();
    }
  };

  return (
    <div
      className="flex flex-nowrap items-center gap-1.5 shrink-0 min-w-0"
      data-tour="nav-equity"
      data-critical-banner={criticalBanner("BOT_RISK") || undefined}
    >
      <AdminOnlyNotice>
        <LlmStatusIndicator />
      </AdminOnlyNotice>

      <div className="relative group shrink-0">
        <div
          role="button"
          tabIndex={0}
          onClick={handleRefresh}
          onKeyDown={handleRefreshKeyDown}
          aria-label="Обновить баланс портфеля"
          aria-busy={refreshing}
          title="Кап = сколько из баланса можно торговать · Баланс = сумма на всех счетах · Торг = в открытых позициях. Нажмите для обновления."
          className={clsx(
            "flex items-center gap-1.5 xl:gap-2 px-1.5 xl:px-2 py-0.5 rounded border border-cockpit-border bg-cockpit-panel/50",
            "cursor-pointer transition-colors duration-150",
            "hover:border-terminal-accent/40 hover:bg-[var(--qa-hover)]",
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-terminal-accent/70",
            (refreshMutation.isPending || isLoading) && "pointer-events-none",
            hasVenues && "pr-2",
          )}
        >
          <LiveDataBadge
            state={isError ? "disconnected" : metricsFreshness.state}
            ageLabel={metricsFreshness.ageLabel}
            compact
            showIcon={false}
            className="mr-0.5"
          />
          <MetricItem
            label="Кап"
            labelShort="Кап"
            value={cap}
            stale={stale}
            title="Лимит торговли: часть баланса, которую платформе разрешено использовать. Не добавляется к балансу."
          />
          <div className="w-px h-4 bg-cockpit-border shrink-0" />
          <MetricItem
            label="Баланс"
            labelShort="Баланс"
            value={balance}
            stale={stale}
            loading={refreshing}
            title={
              accountTotal != null
                ? "Сумма средств на всех подключённых счетах и API-ключах. Кап в эту сумму не входит."
                : "Нет данных по счетам"
            }
          />
          <div className="w-px h-4 bg-cockpit-border shrink-0" />
          <MetricItem
            label="Торг"
            labelShort="Торг"
            value={trading}
            accent
            stale={stale}
            title={pnlTitle}
          />
          {hasVenues && (
            <span className="text-[9px] font-mono text-qa-muted leading-none pointer-events-none" aria-hidden>
              ▾
            </span>
          )}
        </div>

        {hasVenues && (
          <div
            className={clsx(
              "absolute right-0 top-full mt-1 z-50 min-w-[210px]",
              "rounded-md border border-cockpit-border-strong bg-cockpit-surface",
              "p-2.5 space-y-1.5",
              "opacity-0 invisible translate-y-1 pointer-events-none",
              "group-hover:opacity-100 group-hover:visible group-hover:translate-y-0",
              "transition-all duration-150",
            )}
            role="tooltip"
          >
            <div className="text-[9px] uppercase tracking-wider text-qa-muted mb-1">
              Балансы площадок
            </div>
            {venues.map((v) => (
              <div key={v.venue} className="flex items-center justify-between gap-4">
                <span className="text-[11px] text-qa-text">
                  {venueLabel(v.venue)}
                  {v.configured === false && (
                    <span className="text-qa-muted ml-1">(нет ключей)</span>
                  )}
                </span>
                <span className="font-mono text-[11px] tabular-nums text-terminal-up">
                  {formatUsd(v.total_usd ?? v.balance_usd, { compact: false })}
                </span>
              </div>
            ))}
            {venueData?.total_usd != null && (
              <>
                <div className="border-t border-cockpit-border my-1" />
                <div className="flex items-center justify-between gap-4">
                  <span className="text-[10px] uppercase tracking-wide text-qa-muted">Счёт всего</span>
                  <span className="font-mono text-[11px] tabular-nums text-white">
                    {formatUsd(venueData.total_usd, { compact: false })}
                  </span>
                </div>
              </>
            )}
            {allocationUsd != null && (
              <div className="flex items-center justify-between gap-4 pt-1">
                <span className="text-[10px] uppercase tracking-wide text-qa-muted">Лимит торговли</span>
                <span className="font-mono text-[11px] tabular-nums text-qa-text">
                  {formatUsd(allocationUsd, { compact: false })}
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
