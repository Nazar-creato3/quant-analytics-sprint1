"use client";

import { statusLabelRu } from "@/lib/human-ru";

import { useQuery } from "@tanstack/react-query";
import { maneuversApi, settingsApi } from "@/lib/api";
import { OPEN_POSITION_STATUS_FILTER } from "@/lib/maneuvers";
import { Maneuver } from "@/types";
import { clsx } from "clsx";
import { TrendingUp, TrendingDown, Activity, DollarSign, Shield, AlertTriangle } from "lucide-react";
import { StatCard, Skeleton } from "@/components/ui";

export function PortfolioStats() {
  const { data: activePage, isLoading } = useQuery({
    queryKey: ["maneuvers-active"],
    queryFn: () =>
      maneuversApi.list({ status: OPEN_POSITION_STATUS_FILTER, page_size: 100 }),
    refetchInterval: 30_000,
  });

  const { data: userSettings } = useQuery({
    queryKey: ["settings"],
    queryFn: settingsApi.get,
    staleTime: 60_000,
  });

  const { data: filledPage } = useQuery({
    queryKey: ["maneuvers-filled-today"],
    queryFn: () =>
      maneuversApi.list({ status: "filled", page_size: 100 }),
    refetchInterval: 60_000,
  });

  if (isLoading) {
    return (
      <div className="grid grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="stat-card">
            <Skeleton className="h-3 w-24 mb-2" />
            <Skeleton className="h-7 w-16" />
          </div>
        ))}
      </div>
    );
  }

  const executing: Maneuver[] = activePage?.items ?? [];
  const filled: Maneuver[] = filledPage?.items ?? [];

  const totalExposure = executing.reduce((s, m) => s + (m.position_size_usd || 0), 0);
  const realizedPnl   = filled.reduce((s, m) => s + (m.realized_pnl || 0), 0);
  const openCount     = executing.length;

  const portfolioSize = userSettings?.portfolio_size ?? 100_000;
  const exposurePct = portfolioSize > 0 ? (totalExposure / portfolioSize) * 100 : 0;
  const exposureRisk =
    exposurePct > 70 ? "danger" :
    exposurePct > 50 ? "warning" : "success";

  const pnlTrend = realizedPnl > 0 ? "up" : realizedPnl < 0 ? "down" : "neutral";

  return (
    <div className="grid grid-cols-4 gap-3">
      <StatCard
        label="Открытых позиций"
        value={openCount}
        sub={`${executing.map(m => m.ticker).slice(0, 3).join(", ")}${openCount > 3 ? "…" : ""}`}
        trend={openCount > 0 ? "up" : "neutral"}
      />

      <StatCard
        label="Экспозиция"
        value={`$${totalExposure.toLocaleString("en", { maximumFractionDigits: 0 })}`}
        sub={`${exposurePct.toFixed(1)}% портфеля`}
        trend={exposureRisk === "danger" ? "down" : exposureRisk === "warning" ? "neutral" : "up"}
      />

      <StatCard
        label="Реализованный P&L"
        value={
          <span className={clsx(
            realizedPnl > 0 ? "text-terminal-up" : realizedPnl < 0 ? "text-terminal-down" : "text-white"
          )}>
            {realizedPnl >= 0 ? "+" : ""}${realizedPnl.toFixed(0)}
          </span>
        }
        sub={`${filled.length} закрытых сделок`}
        trend={pnlTrend}
      />

      <StatCard
        label="Режим торговли"
        value={
          <span className={clsx(
            "text-base",
            openCount > 0 ? "text-terminal-up" : "text-qa-muted"
          )}>
            PAPER
          </span>
        }
        sub="Live = выключен"
        trend="neutral"
      />
    </div>
  );
}


// ── Open positions table ──────────────────────────────────────────────────────

export function OpenPositions() {
  const { data, isLoading } = useQuery({
    queryKey: ["maneuvers-open-positions"],
    queryFn: () => maneuversApi.list({ status: "filled", page_size: 50 }),
    refetchInterval: 15_000,
  });

  const positions: Maneuver[] = data?.items ?? [];

  if (isLoading) {
    return (
      <div className="card">
        <div className="px-4 py-3 border-b border-qa-border">
          <span className="section-title">Открытые позиции</span>
        </div>
        <div className="p-4 space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-8" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-3 border-b border-qa-border flex items-center justify-between">
        <span className="section-title">Открытые позиции</span>
        <span className="text-xs text-qa-muted">{positions.length} активных</span>
      </div>

      {positions.length === 0 ? (
        <div className="py-8 text-center text-sm text-qa-muted">
          Нет открытых позиций
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                {["Тикер", "Сторона", "Размер", "Вход", "TP", "SL", "Статус"].map(h => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {positions.map(m => (
                <tr key={m.id}>
                  <td className="font-mono font-bold text-white text-xs">{m.ticker}</td>
                  <td>
                    <span className={clsx(
                      "badge text-[10px]",
                      m.direction === "long"
                        ? "text-terminal-up bg-qa-success-bg border-terminal-up/40"
                        : "text-terminal-down bg-qa-danger-bg border-terminal-down/40"
                    )}>
                      {m.direction.toUpperCase()}
                    </span>
                  </td>
                  <td className="text-xs tabular-nums text-qa-text">
                    ${m.position_size_usd.toLocaleString("en", { maximumFractionDigits: 0 })}
                  </td>
                  <td className="text-xs tabular-nums text-qa-muted">
                    {m.fill_price ? `$${m.fill_price.toFixed(2)}` : `$${m.entry_zone_high?.toFixed(2) ?? "—"}`}
                  </td>
                  <td className="text-xs tabular-nums text-terminal-up">
                    {m.take_profit ? `$${m.take_profit.toFixed(2)}` : "—"}
                  </td>
                  <td className="text-xs tabular-nums text-terminal-down">
                    {m.stop_loss ? `$${m.stop_loss.toFixed(2)}` : "—"}
                  </td>
                  <td>
                    <span className="badge text-[10px] text-terminal-accent bg-[var(--qa-active)] border-terminal-accent/40">
                      {statusLabelRu(m.status)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
