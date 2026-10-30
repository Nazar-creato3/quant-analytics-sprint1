"use client";

import { strategyLabelRu, statusLabelRu } from "@/lib/human-ru";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { clsx } from "clsx";
import Link from "next/link";
import { toast } from "react-hot-toast";
import type { AssetCockpitData, ForecastHierarchyView } from "@/types";
import { pct } from "@/lib/forecast-hierarchy";
import { dealIntentsApi } from "@/lib/api";
import { extractErrorMessage } from "@/lib/errors";
import { isPendingDealIntent } from "@/lib/approval";
import { CockpitPanelHeader } from "@/components/operator/CockpitPanelHeader";
import { DealIntentActionBar } from "@/components/operator/DealIntentActionBar";
import { formatUsd } from "@/lib/format";

const STATE_COLORS: Record<string, string> = {
  deep: "text-terminal-up",
  normal: "text-qa-text",
  thin: "text-terminal-accent",
  illiquid: "text-terminal-down",
  tight: "text-terminal-up",
  wide: "text-terminal-accent",
  stressed: "text-terminal-down",
};

const APPROVAL_COLORS: Record<string, string> = {
  approved: "text-terminal-up",
  pending: "text-terminal-accent",
  held: "text-terminal-accent",
  rejected: "text-terminal-down",
  executing: "text-terminal-accent",
  executed: "text-terminal-up",
  draft: "text-qa-muted",
  cancelled: "text-qa-muted",
};

function MetricRow({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-2 py-1 border-b border-cockpit-border/60 last:border-0">
      <span className="text-[10px] uppercase tracking-wide text-qa-text">{label}</span>
      <span className={clsx("text-[11px] font-mono tabular-nums text-qa-text", valueClass)}>
        {value}
      </span>
    </div>
  );
}

interface AssetCockpitRightPanelProps {
  data: AssetCockpitData;
  predictionView?: ForecastHierarchyView | null;
  className?: string;
}

export function AssetCockpitRightPanel({ data, predictionView, className }: AssetCockpitRightPanelProps) {
  const queryClient = useQueryClient();
  const score = data.bot_suitability_score;
  const scoreColor =
    score >= 70 ? "text-terminal-up" : score >= 45 ? "text-terminal-accent" : "text-terminal-down";

  const approveIntentMutation = useMutation({
    mutationFn: (id: string) => dealIntentsApi.approve(id),
    onSuccess: () => {
      toast.success("Deal intent одобрен");
      queryClient.invalidateQueries({ queryKey: ["asset-cockpit", data.symbol] });
      queryClient.invalidateQueries({ queryKey: ["pending-deal-intents"] });
    },
    onError: (err) => toast.error(extractErrorMessage(err, "Ошибка одобрения")),
  });

  const rejectIntentMutation = useMutation({
    mutationFn: (id: string) => dealIntentsApi.reject(id),
    onSuccess: () => {
      toast.success("Deal intent отклонён");
      queryClient.invalidateQueries({ queryKey: ["asset-cockpit", data.symbol] });
      queryClient.invalidateQueries({ queryKey: ["pending-deal-intents"] });
    },
    onError: (err) => toast.error(extractErrorMessage(err, "Ошибка отклонения")),
  });

  const intentBusy = approveIntentMutation.isPending || rejectIntentMutation.isPending;
  const pendingIntents = data.intents.filter((intent) =>
    isPendingDealIntent(intent.status, intent.approval_state),
  );

  return (
    <aside className={clsx("flex flex-col gap-3 min-h-0", className)}>
      <div className="cockpit-panel">
        <CockpitPanelHeader title="Микроструктура" subtitle={data.symbol} />
        <div className="p-3 space-y-0">
          <MetricRow
            label="Ликвидность"
            value={data.liquidity_state}
            valueClass={STATE_COLORS[data.liquidity_state]}
          />
          <MetricRow
            label="Спред"
            value={`${data.spread_state} · ${data.spread_bps.toFixed(1)} bps`}
            valueClass={STATE_COLORS[data.spread_state]}
          />
          <MetricRow label="Сектор" value={data.sector ?? "—"} />
        </div>
      </div>

      <div className="cockpit-panel">
        <CockpitPanelHeader title="Bot Suitability" subtitle="Strategy mesh" />
        <div className="p-3">
          <div className="flex items-end gap-2">
            <span className={clsx("text-3xl font-mono font-bold tabular-nums", scoreColor)}>
              {score}
            </span>
            <span className="text-[10px] text-qa-muted pb-1">/ 100</span>
          </div>
          <div className="h-1.5 bg-qa-border rounded-full mt-2 overflow-hidden">
            <div
              className={clsx(
                "h-full rounded-full",
                score >= 70 ? "bg-terminal-up" : score >= 45 ? "bg-terminal-accent" : "bg-terminal-down",
              )}
              style={{ width: `${score}%` }}
            />
          </div>
          <div className="mt-3 flex flex-wrap gap-1">
            {data.allowed_strategies.map((strategy) => (
              <span
                key={strategy}
                className="text-[9px] uppercase tracking-wide px-1.5 py-0.5 rounded border border-terminal-accent/40 text-terminal-accent bg-[var(--qa-active)]"
              >
                {strategyLabelRu(strategy)}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="cockpit-panel">
        <CockpitPanelHeader title="Correlations" subtitle="Top peers" />
        <div className="p-2 space-y-1">
          {data.correlations.length === 0 ? (
            <p className="text-[11px] text-qa-muted px-1 py-2">Нет данных о связанных бумагах</p>
          ) : (
            data.correlations.map((peer) => (
            <Link
              key={peer.symbol}
              href={`/cockpit/${encodeURIComponent(peer.symbol)}`}
              className="cockpit-feed-item flex items-center justify-between gap-2 text-[11px] hover:border-cockpit-border-strong"
            >
              <span className="font-mono text-qa-text">{peer.symbol}</span>
              <span className="text-[10px] text-qa-muted">{peer.relation}</span>
              <span
                className={clsx(
                  "font-mono tabular-nums",
                  peer.correlation >= 0 ? "text-terminal-up" : "text-terminal-down",
                )}
              >
                {peer.correlation >= 0 ? "+" : ""}
                {peer.correlation.toFixed(2)}
              </span>
            </Link>
            ))
          )}
        </div>
      </div>

      {predictionView && (
        <div className="cockpit-panel">
          <CockpitPanelHeader title="Prediction Layers" subtitle={data.symbol} />
          <div className="p-3 space-y-2">
            {[
              {
                label: "Point",
                value: predictionView.point_forecast.magnitude_ru ?? predictionView.point_forecast.magnitude,
              },
              {
                label: "Interval",
                value: `${(predictionView.interval_forecast.p10 * 100).toFixed(1)}% – ${(predictionView.interval_forecast.p90 * 100).toFixed(1)}%`,
              },
              {
                label: "Action",
                value: predictionView.action_forecast.recommendation.replace(/_/g, " "),
              },
              {
                label: "Calibrated",
                value: pct(predictionView.calibrated_confidence),
              },
            ].map((row) => (
              <MetricRow key={row.label} label={row.label} value={String(row.value)} />
            ))}
          </div>
        </div>
      )}

      {data.sleeve_budget && (
        <div className="cockpit-panel">
          <CockpitPanelHeader title="Sleeve Risk Budget" subtitle={data.sleeve_budget.sleeve_name} />
          <div className="p-3 space-y-0">
            <MetricRow label="Budget" value={formatUsd(data.sleeve_budget.risk_budget)} />
            <MetricRow label="Used" value={formatUsd(data.sleeve_budget.risk_used)} />
            <MetricRow
              label="Remaining"
              value={formatUsd(data.sleeve_budget.risk_remaining)}
              valueClass="text-terminal-up"
            />
            <MetricRow label="Status" value={data.sleeve_budget.status} />
          </div>
        </div>
      )}

      <div className="cockpit-panel flex flex-col min-h-0">
        <CockpitPanelHeader
          title="Deal Intents"
          subtitle="Ожидают решения"
          badge={pendingIntents.length || data.intents.length}
        />
        <div className="p-2 space-y-2 max-h-56 overflow-y-auto">
          {data.intents.length === 0 ? (
            <p className="text-[11px] text-qa-muted px-1 py-2">Нет intents по инструменту</p>
          ) : (
            data.intents.map((intent) => {
              const showActions = isPendingDealIntent(intent.status, intent.approval_state);
              return (
                <div key={intent.id} className="cockpit-feed-item text-[10px]">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-qa-text uppercase">
                      {intent.strategy} · {intent.direction}
                    </span>
                    <span className={clsx("uppercase font-semibold", APPROVAL_COLORS[intent.approval_state])}>
                      {statusLabelRu(intent.approval_state)}
                    </span>
                  </div>
                  <div className="text-qa-muted mt-0.5 flex justify-between">
                    <span>{intent.risk_tag}</span>
                    <span className="tabular-nums">{format(parseISO(intent.created_at), "dd MMM HH:mm")}</span>
                  </div>
                  {showActions && (
                    <DealIntentActionBar
                      dealIntentId={intent.id}
                      label="Deal Intent · ожидает одобрения"
                      busy={intentBusy}
                      compact
                      onApprove={(id) => approveIntentMutation.mutate(id)}
                      onReject={(id) => rejectIntentMutation.mutate(id)}
                    />
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>

      <div className="cockpit-panel flex flex-col min-h-0">
        <CockpitPanelHeader title="Audit Trail" subtitle="Последние действия" />
        <div className="p-2 space-y-1 max-h-36 overflow-y-auto">
          {data.recent_actions.map((entry) => (
            <div key={entry.id} className="cockpit-feed-item text-[10px]">
              <div className="text-qa-text">{entry.action}</div>
              <div className="text-qa-muted mt-0.5 flex justify-between tabular-nums">
                <span>{entry.resource_type ?? "system"}</span>
                <span>{format(parseISO(entry.timestamp), "dd MMM HH:mm")}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
}
