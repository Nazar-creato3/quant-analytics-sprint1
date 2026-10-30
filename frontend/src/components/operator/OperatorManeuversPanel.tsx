"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import Link from "next/link";
import { clsx } from "clsx";
import { ChevronDown, ChevronUp, TrendingDown, TrendingUp, Minus, Loader2 } from "lucide-react";
import { toast } from "react-hot-toast";
import { LivePerformancePanel } from "@/components/monitoring/LivePerformancePanel";
import { maneuversApi } from "@/lib/api";
import { extractErrorMessage } from "@/lib/errors";
import { isPendingApproval } from "@/lib/approval";
import {
  formatManeuverIncomeRange,
  formatManeuverSlotHeadline,
  isManeuverCancellable,
  isTradeableManeuver,
  MANEUVER_APPROVED_TOAST,
} from "@/lib/maneuvers";
import { formatDurationPresets } from "@/lib/duration-i18n";
import { holdingWindowLabelRu } from "@/lib/human-ru";
import { ManeuverIdeaButton } from "./ManeuverIdeaDialog";
import type { Maneuver, ManeuverApprovalOptions, ManeuverReport, StrategyType } from "@/types";
import { STATUS_BADGE_COLORS } from "@/lib/status-colors";

interface OperatorManeuversPanelProps {
  report: ManeuverReport;
  compact?: boolean;
  onEdit?: (maneuver: Maneuver) => void;
}

const STRATEGY_LABELS: Record<StrategyType, string> = {
  momentum: "импульс",
  mean_reversion: "возврат к среднему",
  breakout: "пробой",
  grid: "сетка",
  event_driven: "событие",
  trend_following: "тренд",
  macro: "общий рынок",
  no_trade: "сейчас не входим",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "Ожидает",
  pending_approval: "Ожидает",
  awaiting_approval: "Ожидает",
  approved: "Одобрен",
  rejected: "Отклонён",
  executing: "Исполнение",
  filled: "Исполнен",
  cancelled: "Отменён",
  invalidated: "Недейств.",
};

const STATUS_TITLES: Record<string, string> = {
  rejected:
    "Идея отклонена вручную. Это не автоматический отказ из‑за слабой уверенности.",
};

const DURATION_PRESETS = formatDurationPresets("ru");

function DirectionIcon({ direction }: { direction: string }) {
  if (direction === "long") return <TrendingUp size={12} className="text-terminal-up" />;
  if (direction === "short") return <TrendingDown size={12} className="text-terminal-down" />;
  return <Minus size={12} className="text-qa-muted" />;
}

function RowActions({
  m,
  isPending,
  isNoTrade,
  busy,
  onApprove,
  onReject,
  onClose,
}: {
  m: Maneuver;
  isPending: boolean;
  isNoTrade: boolean;
  busy?: boolean;
  onApprove: (id: string, options?: ManeuverApprovalOptions) => void;
  onReject: (id: string) => void;
  onClose: (id: string) => void;
}) {
  const [durationDraft, setDurationDraft] = useState(m.time_horizon || "7 дней");
  const [expiryDraft, setExpiryDraft] = useState("");

  if (isNoTrade) return null;

  return (
    <div className="flex flex-col gap-1.5">
      {isPending && (
        <>
          <div className="min-w-[12rem] rounded-md border border-terminal-accent/25 bg-terminal-accent/5 p-1.5">
            <div className="flex flex-wrap gap-1 mb-1">
              {DURATION_PRESETS.slice(0, 4).map((preset) => (
                <button
                  key={preset.key}
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setDurationDraft(preset.api);
                    setExpiryDraft("");
                  }}
                  className={clsx(
                    "px-1.5 py-0.5 rounded border text-[9px]",
                    durationDraft === preset.api && !expiryDraft
                      ? "border-terminal-accent/60 text-terminal-accent bg-[var(--qa-active)]"
                      : "border-qa-border text-qa-muted bg-qa-panel-secondary",
                  )}
                >
                  {preset.label}
                </button>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-1">
              <input
                value={durationDraft}
                onChange={(e) => setDurationDraft(e.target.value)}
                disabled={busy}
                placeholder="7 дней"
                className="min-w-0 rounded border border-qa-border bg-qa-panel px-1.5 py-1 text-[10px]"
              />
              <input
                type="datetime-local"
                value={expiryDraft}
                onChange={(e) => setExpiryDraft(e.target.value)}
                disabled={busy}
                title="Точное время закрытия, если нужно"
                className="min-w-0 rounded border border-qa-border bg-qa-panel px-1.5 py-1 text-[10px]"
              />
            </div>
          </div>
          <div className="flex flex-wrap gap-1">
          <ManeuverIdeaButton m={m} />
          <button
            type="button"
            disabled={busy}
            onClick={() =>
              onApprove(m.id, {
                time_horizon: durationDraft.trim() || undefined,
                expiry_at: expiryDraft ? new Date(expiryDraft).toISOString() : undefined,
              })
            }
            className="px-2 py-1 text-[10px] font-bold btn-success disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap inline-flex items-center gap-1"
          >
            {busy ? <Loader2 size={10} className="animate-spin" /> : null}
            Одобрить
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => onReject(m.id)}
            className="px-2 py-1 text-[10px] font-bold btn-danger-solid disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap inline-flex items-center gap-1"
          >
            {busy ? <Loader2 size={10} className="animate-spin" /> : null}
            Отклонить
          </button>
          </div>
        </>
      )}
      {!isPending && isManeuverCancellable(m.status) && (
        <button
          type="button"
          disabled={busy}
          onClick={() => onClose(m.id)}
          className="px-2 py-1 rounded text-[10px] font-semibold text-qa-text border border-qa-border-strong hover:bg-[var(--qa-hover)] disabled:opacity-50"
        >
          Закрыть
        </button>
      )}
      <Link
        href={`/cockpit/${encodeURIComponent(m.ticker)}`}
        className="px-2 py-1 rounded text-[10px] font-semibold text-terminal-accent border border-terminal-accent/40 hover:bg-[var(--qa-active)] whitespace-nowrap"
      >
        Карточка
      </Link>
    </div>
  );
}

function OperatorManeuverRow({
  m,
  busy,
  onApprove,
  onReject,
  onClose,
}: {
  m: Maneuver;
  busy?: boolean;
  onApprove: (id: string, options?: ManeuverApprovalOptions) => void;
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
          isNoTrade && "opacity-50",
        )}
        onClick={() => setExpanded((v) => !v)}
      >
        <td className="px-2 py-2 text-center">
          <span className="text-[10px] font-bold text-qa-muted w-5 h-5 inline-flex items-center justify-center rounded border border-qa-border-strong">
            {m.rank}
          </span>
        </td>
        <td className="px-2 py-2">
          <div className="flex items-center gap-1.5">
            <DirectionIcon direction={m.direction} />
            <span className="font-mono font-semibold text-white text-xs">{m.ticker}</span>
          </div>
          <div className="text-[10px] text-qa-muted">{STRATEGY_LABELS[m.strategy_type]}</div>
        </td>
        <td className="px-2 py-2 text-[10px] tabular-nums text-qa-text hidden sm:table-cell">
          {m.entry_zone_low && m.entry_zone_high
            ? `${m.entry_zone_low.toFixed(2)}–${m.entry_zone_high.toFixed(2)}`
            : "—"}
        </td>
        <td className="px-2 py-2 text-[10px] tabular-nums text-terminal-up font-medium">
          {formatManeuverIncomeRange(m)}
        </td>
        <td className="px-2 py-2 hidden md:table-cell">
          <span
            className={clsx(
              "text-[10px] font-medium px-1.5 py-0.5 rounded border uppercase",
              STATUS_BADGE_COLORS[m.status] || "text-qa-muted bg-qa-panel-secondary border-qa-border-strong",
            )}
            title={STATUS_TITLES[m.status]}
          >
            {STATUS_LABELS[m.status] ?? m.status.replace(/_/g, " ")}
          </span>
        </td>
        <td className="px-2 py-2 align-top" onClick={(e) => e.stopPropagation()}>
          <RowActions
            m={m}
            isPending={isPending}
            isNoTrade={isNoTrade}
            busy={busy}
            onApprove={onApprove}
            onReject={onReject}
            onClose={onClose}
          />
        </td>
      </tr>
      {expanded && (
        <tr className="bg-qa-panel-secondary/40 border-b border-qa-border">
          <td colSpan={6} className="px-4 py-3 text-[11px]">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <h4 className="text-[10px] font-semibold text-qa-muted uppercase mb-1">Почему идея</h4>
                <p className="text-qa-text leading-relaxed">{m.rationale || "—"}</p>
                {m.regime_context && (
                  <p className="mt-2 text-qa-muted leading-relaxed">{m.regime_context}</p>
                )}
                {m.key_drivers && m.key_drivers.length > 0 && (
                  <ul className="mt-2 space-y-1 text-qa-muted">
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
                <h4 className="text-[10px] font-semibold text-qa-muted uppercase mb-1">Почему сейчас</h4>
                <p className="text-qa-text leading-relaxed">{m.catalyst || "—"}</p>
                {m.risk_flags && m.risk_flags.length > 0 && (
                  <ul className="mt-2 text-qa-warning space-y-0.5">
                    {m.risk_flags.map((flag) => (
                      <li key={flag}>⚠ {flag}</li>
                    ))}
                  </ul>
                )}
                {m.signal_meta?.horizon_profiles && typeof m.signal_meta.horizon_profiles === "object" ? (
                  <div className="mt-2 text-[10px] text-qa-muted space-y-0.5">
                    <div className="uppercase">Сроки</div>
                    {Object.entries(m.signal_meta.horizon_profiles as Record<string, string>).map(([key, value]) => (
                      <div key={key}>
                        {holdingWindowLabelRu(key)}: {value}
                      </div>
                    ))}
                  </div>
                ) : null}
                <div className="mt-2 flex flex-wrap gap-3 text-[10px] text-qa-muted tabular-nums">
                  <span>Размер ${m.position_size_usd.toLocaleString("ru", { maximumFractionDigits: 0 })}</span>
                  <span>
                    цель / стоп{" "}
                    {m.take_profit?.toFixed(2) ?? "—"} / {m.stop_loss?.toFixed(2) ?? "—"}
                  </span>
                  <span>уверенность {(m.confidence * 100).toFixed(0)}%</span>
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export function OperatorManeuversPanel({ report, compact = false }: OperatorManeuversPanelProps) {
  const queryClient = useQueryClient();
  const [collapsed, setCollapsed] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["report", report.id] });
    queryClient.invalidateQueries({ queryKey: ["decision-feed-latest-report"] });
    queryClient.invalidateQueries({ queryKey: ["decision-feed-pending-maneuvers"] });
    queryClient.invalidateQueries({ queryKey: ["pending-approvals"] });
    queryClient.invalidateQueries({ queryKey: ["decision-feed-reports"] });
    queryClient.invalidateQueries({ queryKey: ["bottom-positions"] });
    queryClient.invalidateQueries({ queryKey: ["bottom-orders"] });
    queryClient.invalidateQueries({ queryKey: ["maneuvers-open-positions"] });
    queryClient.invalidateQueries({ queryKey: ["operator-open-positions"] });
  };

  const approveMutation = useMutation({
    mutationFn: ({ id, options }: { id: string; options?: ManeuverApprovalOptions }) =>
      maneuversApi.approve(id, undefined, options),
    onMutate: ({ id }) => setBusyId(id),
    onSettled: () => setBusyId(null),
    onSuccess: () => {
      toast.success(MANEUVER_APPROVED_TOAST);
      invalidate();
    },
    onError: (err) => toast.error(extractErrorMessage(err, "Не удалось одобрить")),
  });

  const rejectMutation = useMutation({
    mutationFn: (id: string) => maneuversApi.reject(id),
    onMutate: (id) => setBusyId(id),
    onSettled: () => setBusyId(null),
    onSuccess: () => {
      toast.success("Отклонено");
      invalidate();
    },
    onError: (err) => toast.error(extractErrorMessage(err, "Не удалось отклонить")),
  });

  const cancelMutation = useMutation({
    mutationFn: (id: string) => maneuversApi.cancel(id),
    onMutate: (id) => setBusyId(id),
    onSettled: () => setBusyId(null),
    onSuccess: (result) => {
      toast.success(result.message || "Закрыто");
      invalidate();
    },
    onError: (err) => toast.error(extractErrorMessage(err, "Не удалось закрыть")),
  });

  const slotHeadline = formatManeuverSlotHeadline(report);
  const busy = approveMutation.isPending || rejectMutation.isPending || cancelMutation.isPending;

  return (
    <div
      className={clsx(
        "rounded-lg border border-qa-border overflow-hidden flex flex-col min-w-0 w-full bg-qa-bg/40",
        compact ? "flex-1 min-h-0" : "max-h-[480px]",
      )}
    >
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="px-3 py-2 bg-qa-panel-secondary/80 border-b border-qa-border flex items-center justify-between gap-2 text-left shrink-0 hover:bg-qa-panel-secondary"
      >
        <div className="flex items-center gap-2 min-w-0">
          {collapsed ? (
            <ChevronDown size={14} className="text-qa-muted shrink-0" />
          ) : (
            <ChevronUp size={14} className="text-qa-muted shrink-0" />
          )}
            <div className="min-w-0">
            <h3 className="text-xs font-semibold text-white truncate">
              {slotHeadline.title}
            </h3>
            <p className="text-[10px] text-qa-muted truncate">
              {format(new Date(report.created_at), "dd MMM yyyy, HH:mm")} ·{" "}
              <span className="text-terminal-accent">{report.regime || "фон неясен"}</span> ·{" "}
              <span className="text-terminal-up">{slotHeadline.subtitleTradeable}</span>
            </p>
          </div>
        </div>
      </button>

      {!collapsed && (
        <div className="overflow-x-auto overflow-y-auto flex-1 min-h-0">
          <table className="w-full text-xs min-w-[520px]">
            <thead>
              <tr className="border-b border-qa-border bg-qa-panel-secondary/50 sticky top-0 z-10">
                {["#", "Бумага", "Вход", "Доход", "Статус", "Действия"].map((h) => (
                  <th
                    key={h}
                    className={clsx(
                      "px-2 py-1.5 text-left text-[10px] font-medium text-qa-muted uppercase tracking-wider whitespace-nowrap",
                      h === "Вход" && "hidden sm:table-cell",
                      h === "Статус" && "hidden md:table-cell",
                    )}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {report.maneuvers.map((m) => (
                <OperatorManeuverRow
                  key={m.id}
                  m={m}
                  busy={busy && busyId === m.id}
                  onApprove={(id, options) => approveMutation.mutate({ id, options })}
                  onReject={(id) => rejectMutation.mutate(id)}
                  onClose={(id) => cancelMutation.mutate(id)}
                />
              ))}
            </tbody>
          </table>
          {!compact && (
            <div className="p-3 border-t border-qa-border">
              <LivePerformancePanel />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
