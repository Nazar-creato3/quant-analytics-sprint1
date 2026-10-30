"use client";

import { statusLabelRu } from "@/lib/human-ru";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { maneuversApi } from "@/lib/api";
import { extractErrorMessage } from "@/lib/errors";
import { Maneuver, ManeuverReport, StrategyType } from "@/types";
import { toast } from "react-hot-toast";
import { ChevronDown, ChevronUp, TrendingUp, TrendingDown, Minus } from "lucide-react";
import Link from "next/link";
import { clsx } from "clsx";
import { format } from "date-fns";
import { formatManeuverIncomeRange, formatManeuverSlotHeadline, isManeuverCancellable, isTradeableManeuver, MANEUVER_APPROVED_TOAST } from "@/lib/maneuvers";
import { isPendingApproval } from "@/lib/approval";
import { STATUS_BADGE_COLORS } from "@/lib/status-colors";
import { LivePerformancePanel } from "@/components/monitoring/LivePerformancePanel";

interface ManeuversTableProps {
  report: ManeuverReport;
}

const STRATEGY_LABELS: Record<StrategyType, string> = {
  momentum: "Моментум",
  mean_reversion: "Реверсия",
  breakout: "Пробой",
  grid: "Сетка",
  event_driven: "Событие",
  trend_following: "Тренд",
  macro: "Макро",
  no_trade: "Нет сделки",
};

const STATUS_COLORS = STATUS_BADGE_COLORS;

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 70 ? "bg-terminal-up" : pct >= 55 ? "bg-terminal-accent" : "bg-terminal-down";
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 bg-qa-border rounded-full overflow-hidden">
        <div className={clsx("h-full rounded-full", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-qa-muted">{pct}%</span>
    </div>
  );
}

function DirectionIcon({ direction }: { direction: string }) {
  if (direction === "long") return <TrendingUp size={14} className="text-terminal-up" />;
  if (direction === "short") return <TrendingDown size={14} className="text-terminal-down" />;
  return <Minus size={14} className="text-qa-muted" />;
}

function ManeuverRowActions({
  m,
  isPending,
  isNoTrade,
  onApprove,
  onReject,
  onClose,
}: {
  m: Maneuver;
  isPending: boolean;
  isNoTrade: boolean;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onClose: (id: string) => void;
}) {
  if (isNoTrade) return null;

  return (
    <div className="flex flex-wrap gap-1 min-w-[11rem]">
      {isPending ? (
        <>
          <button
            type="button"
            onClick={() => onApprove(m.id)}
            className="px-2 py-1 text-[10px] font-bold btn-success whitespace-nowrap"
          >
            Одобрить
          </button>
          <button
            type="button"
            onClick={() => onReject(m.id)}
            className="px-2 py-1 text-[10px] font-bold btn-danger-solid whitespace-nowrap"
          >
            Отклонить
          </button>
        </>
      ) : isManeuverCancellable(m.status) ? (
        <button
          type="button"
          onClick={() => onClose(m.id)}
          className="px-2 py-1 rounded text-[10px] font-semibold text-qa-text border border-qa-border-strong hover:bg-[var(--qa-hover)]"
          title="Close"
        >
          Закрыть
        </button>
      ) : null}
      <Link
        href={`/cockpit/${encodeURIComponent(m.ticker)}`}
        className="px-2 py-1 rounded text-[10px] font-semibold text-terminal-accent border border-terminal-accent/40 hover:bg-[var(--qa-active)] whitespace-nowrap"
      >
        Карточка
      </Link>
    </div>
  );
}

function ManeuverRow({ m, onApprove, onReject, onClose }: {
  m: Maneuver;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onClose: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const isNoTrade = !isTradeableManeuver(m);
  const isPending = isPendingApproval(m.status);

  return (
    <>
      <tr
        className={clsx(
          "border-b border-qa-border hover:bg-qa-panel-secondary/50 transition-colors cursor-pointer",
          isNoTrade && "opacity-50"
        )}
        onClick={() => setExpanded(!expanded)}
      >
        {/* Rank */}
        <td className="px-3 py-3 text-center">
          <span className="text-xs font-bold text-qa-muted w-6 h-6 inline-flex items-center justify-center rounded border border-qa-border-strong">
            {m.rank}
          </span>
        </td>

        {/* Ticker + direction */}
        <td className="px-3 py-3">
          <div className="flex items-center gap-2">
            <DirectionIcon direction={m.direction} />
            <span className="font-mono font-semibold text-white text-sm">{m.ticker}</span>
          </div>
          <div className="text-xs text-qa-muted mt-0.5">
            {STRATEGY_LABELS[m.strategy_type]}
          </div>
        </td>

        {/* Entry zone */}
        <td className="px-3 py-3 text-xs tabular-nums text-qa-text">
          {m.entry_zone_low && m.entry_zone_high
            ? `${m.entry_zone_low.toFixed(2)} – ${m.entry_zone_high.toFixed(2)}`
            : "—"}
        </td>

        {/* TP / SL */}
        <td className="px-3 py-3 text-xs tabular-nums">
          {m.take_profit
            ? <span className="text-terminal-up">{m.take_profit.toFixed(2)}</span>
            : <span className="text-qa-muted">—</span>}
          {" / "}
          {m.stop_loss
            ? <span className="text-terminal-down">{m.stop_loss.toFixed(2)}</span>
            : <span className="text-qa-muted">—</span>}
        </td>

        {/* Position size */}
        <td className="px-3 py-3 text-xs tabular-nums text-qa-text">
          {m.position_size_usd > 0
            ? `$${m.position_size_usd.toLocaleString("en", { maximumFractionDigits: 0 })}`
            : "—"}
        </td>

        {/* Expected return */}
        <td className="px-3 py-3 text-xs tabular-nums">
          {formatManeuverIncomeRange(m) !== "—"
            ? <span className="text-terminal-up">{formatManeuverIncomeRange(m)}</span>
            : <span className="text-qa-muted">—</span>}
        </td>

        {/* Risk % */}
        <td className="px-3 py-3 text-xs text-terminal-down tabular-nums">
          {m.risk_percent > 0 ? `${m.risk_percent.toFixed(1)}%` : "—"}
        </td>

        {/* Confidence */}
        <td className="px-3 py-3">
          <ConfidenceBar value={m.confidence} />
        </td>

        {/* Horizon */}
        <td className="px-3 py-3 text-xs text-qa-muted">{m.time_horizon}</td>

        {/* Status */}
        <td className="px-3 py-3">
          <span className={clsx(
            "text-xs font-medium px-2 py-0.5 rounded border",
            STATUS_COLORS[m.status] || "text-qa-muted bg-qa-panel-secondary border-qa-border-strong"
          )}>
            {statusLabelRu(m.status)}
          </span>
        </td>

        {/* Actions */}
        <td className="px-2 py-2 align-top">
          <div onClick={(e) => e.stopPropagation()}>
            <ManeuverRowActions
              m={m}
              isPending={isPending}
              isNoTrade={isNoTrade}
              onApprove={onApprove}
              onReject={onReject}
              onClose={onClose}
            />
          </div>
        </td>
      </tr>

      {/* Expanded detail row */}
      {expanded && (
        <tr className="bg-qa-panel-secondary/40 border-b border-qa-border">
          <td colSpan={11} className="px-6 py-4">
            <div className="grid grid-cols-2 gap-6 text-sm">
              <div>
                <h4 className="text-xs font-semibold text-qa-muted uppercase tracking-wider mb-2">Обоснование</h4>
                <p className="text-qa-text leading-relaxed">{m.rationale || "—"}</p>
                {m.regime_context && (
                  <p className="mt-2 text-qa-muted leading-relaxed text-xs">{m.regime_context}</p>
                )}
                {m.key_drivers && m.key_drivers.length > 0 && (
                  <ul className="mt-2 space-y-1 text-xs text-qa-muted">
                    {m.key_drivers.map((d) => (
                      <li key={d.feature}>
                        {d.label || d.feature}: {d.contribution > 0 ? "+" : ""}
                        {d.contribution.toFixed(3)}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div>
                <h4 className="text-xs font-semibold text-qa-muted uppercase tracking-wider mb-2">Катализатор</h4>
                <p className="text-qa-text leading-relaxed">{m.catalyst || "—"}</p>
                {m.risk_flags && m.risk_flags.length > 0 && (
                  <ul className="mt-2 text-qa-warning space-y-0.5 text-xs">
                    {m.risk_flags.map((flag) => (
                      <li key={flag}>⚠ {flag}</li>
                    ))}
                  </ul>
                )}
                <h4 className="text-xs font-semibold text-qa-muted uppercase tracking-wider mt-3 mb-2">План исполнения</h4>
                <p className="text-qa-text leading-relaxed text-xs font-mono">{m.execution_plan || "—"}</p>
                {m.suggested_position_pct != null && (
                  <p className="mt-2 text-xs text-qa-muted">
                    Реком. размер: {m.suggested_position_pct.toFixed(2)}% портфеля
                  </p>
                )}
              </div>
            </div>
            {m.invalidation_level && (
              <div className="mt-3 text-xs text-terminal-accent">
                ⚠ Уровень инвалидации: <span className="font-mono">{m.invalidation_level.toFixed(4)}</span>
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

export function ManeuversTable({ report }: ManeuversTableProps) {
  const queryClient = useQueryClient();
  const [collapsed, setCollapsed] = useState(false);

  const approveMutation = useMutation({
    mutationFn: (id: string) => maneuversApi.approve(id),
    onSuccess: () => {
      toast.success(MANEUVER_APPROVED_TOAST);
      queryClient.invalidateQueries({ queryKey: ["report", report.id] });
      queryClient.invalidateQueries({ queryKey: ["decision-feed-latest-report"] });
      queryClient.invalidateQueries({ queryKey: ["decision-feed-pending-maneuvers"] });
      queryClient.invalidateQueries({ queryKey: ["pending-approvals"] });
    },
    onError: () => toast.error("Ошибка при одобрении"),
  });

  const rejectMutation = useMutation({
    mutationFn: (id: string) => maneuversApi.reject(id),
    onSuccess: () => {
      toast.success("Маневр отклонён");
      queryClient.invalidateQueries({ queryKey: ["report", report.id] });
      queryClient.invalidateQueries({ queryKey: ["decision-feed-latest-report"] });
      queryClient.invalidateQueries({ queryKey: ["decision-feed-pending-maneuvers"] });
      queryClient.invalidateQueries({ queryKey: ["pending-approvals"] });
    },
    onError: () => toast.error("Ошибка при отклонении"),
  });

  const cancelMutation = useMutation({
    mutationFn: (id: string) => maneuversApi.cancel(id),
    onSuccess: (result) => {
      toast.success(result.message || "Maneuver closed");
      queryClient.invalidateQueries({ queryKey: ["report", report.id] });
    },
    onError: (err) => toast.error(extractErrorMessage(err, "Не удалось отменить маневр")),
  });

  const slotHeadline = formatManeuverSlotHeadline(report);

  return (
    <div className="space-y-3">
      <LivePerformancePanel />
      <div className="rounded-xl border border-qa-border overflow-hidden flex flex-col max-h-[min(520px,50vh)] min-w-0 w-full">
      {/* Report header */}
      <div className="px-4 py-3 bg-qa-panel-secondary border-b border-qa-border flex items-center justify-between shrink-0">
        <button
          type="button"
          onClick={() => setCollapsed(c => !c)}
          className="flex items-center gap-2 text-left group"
        >
          {collapsed ? <ChevronDown size={16} className="text-qa-muted" /> : <ChevronUp size={16} className="text-qa-muted" />}
          <div>
            <h2 className="text-sm font-semibold text-white group-hover:text-terminal-accent">
              {slotHeadline.title}
            </h2>
            <p className="text-xs text-qa-muted mt-0.5">
              {format(new Date(report.created_at), "dd MMM yyyy, HH:mm")} UTC ·
              Режим: <span className="text-terminal-accent">{report.regime || "N/A"}</span> ·
              Торгуемых: <span className="text-terminal-up">{slotHeadline.subtitleTradeable}</span>
            </p>
          </div>
        </button>
        <span className={clsx(
          "text-xs px-2 py-1 rounded border",
          report.market_context?.triggered_by === "scheduler"
            ? "text-terminal-accent bg-[var(--qa-active)] border-terminal-accent/40"
            : "text-qa-muted bg-qa-panel-secondary border-qa-border-strong"
        )}>
          {String(report.market_context?.trading_mode || "paper").toUpperCase()}
        </span>
      </div>

      {/* Table — scrollable body */}
      {!collapsed && (
      <div className="overflow-x-auto overflow-y-auto flex-1 min-h-0 min-w-0 w-full">
        <table className="w-full text-sm min-w-[860px]">
          <thead>
            <tr className="border-b border-qa-border bg-qa-panel-secondary/50 sticky top-0 z-10">
              {["#", "Тикер", "Вход", "TP / SL", "Размер", "Доход", "Риск", "Уверен.", "Горизонт", "Статус", "Действия"].map(h => (
                <th key={h} className="px-2 py-2 text-left text-xs font-medium text-qa-muted uppercase tracking-wider whitespace-nowrap">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {report.maneuvers.map(m => (
              <ManeuverRow
                key={m.id}
                m={m}
                onApprove={(id) => approveMutation.mutate(id)}
                onReject={(id) => rejectMutation.mutate(id)}
                onClose={(id) => cancelMutation.mutate(id)}
              />
            ))}
          </tbody>
        </table>
      </div>
      )}

      {/* Text summary footer */}
      {!collapsed && report.text_summary && (
        <details className="border-t border-qa-border">
          <summary className="px-4 py-2 text-xs text-qa-muted cursor-pointer hover:text-qa-text">
            Текстовое резюме ↓
          </summary>
          <pre className="px-4 py-3 text-xs text-qa-muted font-mono whitespace-pre-wrap bg-qa-bg leading-relaxed">
            {report.text_summary}
          </pre>
        </details>
      )}
    </div>
    </div>
  );
}
