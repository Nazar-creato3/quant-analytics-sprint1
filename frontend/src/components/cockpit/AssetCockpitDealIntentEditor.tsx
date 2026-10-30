"use client";

import { strategyLabelRu, statusLabelRu } from "@/lib/human-ru";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Loader2, Save, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "react-hot-toast";
import { CockpitPanelHeader } from "@/components/operator/CockpitPanelHeader";
import { DealIntentActionBar } from "@/components/operator/DealIntentActionBar";
import { isPendingDealIntent } from "@/lib/approval";
import { dealIntentsApi } from "@/lib/api";
import {
  OPEN_DEAL_INTENT_STATUSES,
  PENDING_DEAL_INTENT_EDIT_STATUSES,
  buildExitLogicPatch,
  draftsFromIntent,
} from "@/lib/deal-intent-exit-logic";
import { extractErrorMessage } from "@/lib/errors";
import type { CockpitIntentSummary } from "@/types";

const fieldClass =
  "input text-xs font-mono tabular-nums py-2 px-2.5 rounded-md w-full";

interface AssetCockpitDealIntentEditorProps {
  symbol: string;
  intentSummaries: CockpitIntentSummary[];
}

function pickEditableIntent(summaries: CockpitIntentSummary[]): CockpitIntentSummary | undefined {
  const pending = summaries.find((s) =>
    PENDING_DEAL_INTENT_EDIT_STATUSES.has(s.status.toLowerCase()) ||
    isPendingDealIntent(s.status, s.approval_state),
  );
  if (pending) return pending;
  return summaries.find((s) => OPEN_DEAL_INTENT_STATUSES.has(s.status.toLowerCase()));
}

export function AssetCockpitDealIntentEditor({
  symbol,
  intentSummaries,
}: AssetCockpitDealIntentEditorProps) {
  const queryClient = useQueryClient();
  const summary = pickEditableIntent(intentSummaries);
  const isOpen = summary ? OPEN_DEAL_INTENT_STATUSES.has(summary.status.toLowerCase()) : false;
  const isPending = summary ? !isOpen : false;

  const { data: intent, isLoading } = useQuery({
    queryKey: ["cockpit-deal-intent", summary?.id],
    queryFn: () => dealIntentsApi.get(summary!.id),
    enabled: !!summary?.id,
  });

  const [dirty, setDirty] = useState(false);
  const [targetPrice, setTargetPrice] = useState("");
  const [direction, setDirection] = useState<"long" | "short">("long");
  const [requiredConfidence, setRequiredConfidence] = useState("");
  const [maxSlippageBps, setMaxSlippageBps] = useState("");
  const [maxSpreadBps, setMaxSpreadBps] = useState("");
  const [timeInForce, setTimeInForce] = useState("day");
  const [triggerType, setTriggerType] = useState("limit");
  const [approvalThreshold, setApprovalThreshold] = useState("");
  const [riskTag, setRiskTag] = useState("medium");
  const [hedgeAttachmentId, setHedgeAttachmentId] = useState("");
  const [exitDraft, setExitDraft] = useState({
    stopLoss: "",
    takeProfit: "",
    trailingPct: "",
    partialClosePct: "",
    timeExitHours: "",
    positionSizeUsd: "",
  });

  const patchExit = (partial: Partial<typeof exitDraft>) => {
    setDirty(true);
    setExitDraft((d) => ({ ...d, ...partial }));
  };

  useEffect(() => {
    if (!intent || dirty) return;
    setTargetPrice(intent.target_price?.toString() ?? "");
    setDirection(intent.direction === "short" ? "short" : "long");
    setRequiredConfidence(String(intent.required_confidence));
    setMaxSlippageBps(String(intent.max_slippage_bps));
    setMaxSpreadBps(String(intent.max_spread_bps));
    setTimeInForce(intent.time_in_force || "day");
    setTriggerType(intent.trigger_type || "limit");
    setApprovalThreshold(String(intent.approval_threshold));
    setRiskTag(intent.risk_tag || "medium");
    setHedgeAttachmentId(intent.hedge_attachment_id ?? "");
    setExitDraft(draftsFromIntent(intent));
  }, [intent, dirty]);

  const resetDrafts = () => {
    if (!intent) return;
    setDirty(false);
    setTargetPrice(intent.target_price?.toString() ?? "");
    setDirection(intent.direction === "short" ? "short" : "long");
    setRequiredConfidence(String(intent.required_confidence));
    setMaxSlippageBps(String(intent.max_slippage_bps));
    setMaxSpreadBps(String(intent.max_spread_bps));
    setTimeInForce(intent.time_in_force || "day");
    setTriggerType(intent.trigger_type || "limit");
    setApprovalThreshold(String(intent.approval_threshold));
    setRiskTag(intent.risk_tag || "medium");
    setHedgeAttachmentId(intent.hedge_attachment_id ?? "");
    setExitDraft(draftsFromIntent(intent));
  };

  const mark =
    <T,>(setter: (v: T) => void) =>
    (v: T) => {
      setDirty(true);
      setter(v);
    };

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["asset-cockpit", symbol] });
    queryClient.invalidateQueries({ queryKey: ["cockpit-deal-intent", summary?.id] });
    queryClient.invalidateQueries({ queryKey: ["pending-deal-intents"] });
  };

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!intent) throw new Error("No intent");
      const fullExit = buildExitLogicPatch(exitDraft);
      let exit_logic: Record<string, unknown>;
      if (isOpen) {
        exit_logic = {};
        for (const key of ["stop_loss", "take_profit", "trailing", "partial_close"] as const) {
          if (fullExit[key] != null) exit_logic[key] = fullExit[key];
        }
      } else {
        exit_logic = fullExit;
      }
      const body: Parameters<typeof dealIntentsApi.edit>[1] = {
        exit_logic,
        note: "Edited in Asset Cockpit (DealIntent)",
      };
      if (!isOpen) {
        const tp = targetPrice.trim() ? parseFloat(targetPrice) : undefined;
        const conf = requiredConfidence.trim() ? parseFloat(requiredConfidence) : undefined;
        const slip = maxSlippageBps.trim() ? parseInt(maxSlippageBps, 10) : undefined;
        const spread = maxSpreadBps.trim() ? parseInt(maxSpreadBps, 10) : undefined;
        const appr = approvalThreshold.trim() ? parseFloat(approvalThreshold) : undefined;
        if (tp != null && Number.isFinite(tp)) body.target_price = tp;
        body.direction = direction;
        if (conf != null && Number.isFinite(conf)) body.required_confidence = conf;
        if (slip != null && Number.isFinite(slip)) body.max_slippage_bps = slip;
        if (spread != null && Number.isFinite(spread)) body.max_spread_bps = spread;
        body.time_in_force = timeInForce;
        body.trigger_type = triggerType;
        if (appr != null && Number.isFinite(appr)) body.approval_threshold = appr;
        body.risk_tag = riskTag;
        body.hedge_attachment_id = hedgeAttachmentId.trim() || null;
      }
      return dealIntentsApi.edit(intent.id, body);
    },
    onSuccess: () => {
      toast.success("DealIntent сохранён");
      setDirty(false);
      invalidate();
    },
    onError: (err) => toast.error(extractErrorMessage(err, "Save failed")),
  });

  const approveMutation = useMutation({
    mutationFn: (id: string) => dealIntentsApi.approve(id, "Approved from Cockpit after edit"),
    onSuccess: () => {
      toast.success("Одобрено");
      setDirty(false);
      invalidate();
    },
    onError: (err) => toast.error(extractErrorMessage(err, "Approve failed")),
  });

  const rejectMutation = useMutation({
    mutationFn: (id: string) => dealIntentsApi.reject(id),
    onSuccess: () => {
      toast.success("Отклонено");
      setDirty(false);
      invalidate();
    },
    onError: (err) => toast.error(extractErrorMessage(err, "Reject failed")),
  });

  const busy = saveMutation.isPending || approveMutation.isPending || rejectMutation.isPending;

  const subtitle = useMemo(() => {
    if (!summary) return "Нет DealIntent";
    if (isPending) return "Ожидает решения · DealIntent";
    if (isOpen) return "Открытая позиция · только выход";
    return summary.status;
  }, [summary, isPending, isOpen]);

  if (!summary) {
    return null;
  }

  return (
    <div className="cockpit-panel overflow-hidden">
      <CockpitPanelHeader title="Deal Intent" subtitle={subtitle} />
      <div className="p-4">
        {isLoading || !intent ? (
          <div className="h-24 skeleton rounded-md" />
        ) : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2 text-[11px] pb-3 border-b border-cockpit-border/60">
              <span className="font-mono font-bold text-white">{symbol}</span>
              <span className="px-1.5 py-0.5 rounded bg-[var(--qa-active)] text-terminal-accent border border-terminal-accent/40 uppercase text-[10px]">
                {strategyLabelRu(intent.strategy)}
              </span>
              <span className="px-1.5 py-0.5 rounded bg-[var(--qa-active)] text-terminal-accent border border-terminal-accent/40 uppercase text-[10px]">
                {statusLabelRu(intent.status)}
              </span>
              <span className="text-terminal-up tabular-nums ml-auto">
                conf {(intent.required_confidence * 100).toFixed(0)}%
              </span>
            </div>

            {isOpen && (
              <p className="text-[11px] text-qa-muted leading-relaxed border border-cockpit-border/50 rounded-md px-3 py-2 bg-black/20">
                Для открытой позиции доступны только параметры выхода: take-profit, stop-loss,
                trailing stop и частичное закрытие (partial close). Entry, direction и лимиты
                исполнения изменить нельзя.
              </p>
            )}

            {!isOpen && (
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                <label className="space-y-1">
                  <span className="text-[10px] uppercase tracking-wide text-qa-muted font-semibold">
                    Целевая цена
                  </span>
                  <input
                    type="number"
                    step="0.01"
                    value={targetPrice}
                    onChange={(e) => mark(setTargetPrice)(e.target.value)}
                    className={fieldClass}
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-[10px] uppercase tracking-wide text-qa-muted font-semibold">
                    Направление
                  </span>
                  <select
                    value={direction}
                    onChange={(e) => mark(setDirection)(e.target.value as "long" | "short")}
                    className={fieldClass}
                  >
                    <option value="long">Покупка</option>
                    <option value="short">Продажа</option>
                  </select>
                </label>
                <label className="space-y-1">
                  <span className="text-[10px] uppercase tracking-wide text-qa-muted font-semibold">
                    Условие
                  </span>
                  <select
                    value={triggerType}
                    onChange={(e) => mark(setTriggerType)(e.target.value)}
                    className={fieldClass}
                  >
                    {["market", "limit", "stop", "condition"].map((v) => (
                      <option key={v} value={v}>
                        {v}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="space-y-1">
                  <span className="text-[10px] uppercase tracking-wide text-qa-muted font-semibold">
                    Срок действия
                  </span>
                  <select
                    value={timeInForce}
                    onChange={(e) => mark(setTimeInForce)(e.target.value)}
                    className={fieldClass}
                  >
                    {["day", "gtc", "ioc", "fok", "gtd"].map((v) => (
                      <option key={v} value={v}>
                        {v.toUpperCase()}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="space-y-1">
                  <span className="text-[10px] uppercase tracking-wide text-qa-muted font-semibold">
                    Мин. уверенность
                  </span>
                  <input
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    value={requiredConfidence}
                    onChange={(e) => mark(setRequiredConfidence)(e.target.value)}
                    className={fieldClass}
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-[10px] uppercase tracking-wide text-qa-muted font-semibold">
                    Порог одобрения
                  </span>
                  <input
                    type="number"
                    step="0.01"
                    min={0}
                    value={approvalThreshold}
                    onChange={(e) => mark(setApprovalThreshold)(e.target.value)}
                    className={fieldClass}
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-[10px] uppercase tracking-wide text-qa-muted font-semibold">
                    Max slippage (bps)
                  </span>
                  <input
                    type="number"
                    step="1"
                    min={0}
                    value={maxSlippageBps}
                    onChange={(e) => mark(setMaxSlippageBps)(e.target.value)}
                    className={fieldClass}
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-[10px] uppercase tracking-wide text-qa-muted font-semibold">
                    Max spread (bps)
                  </span>
                  <input
                    type="number"
                    step="1"
                    min={0}
                    value={maxSpreadBps}
                    onChange={(e) => mark(setMaxSpreadBps)(e.target.value)}
                    className={fieldClass}
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-[10px] uppercase tracking-wide text-qa-muted font-semibold">
                    Метка риска
                  </span>
                  <select
                    value={riskTag}
                    onChange={(e) => mark(setRiskTag)(e.target.value)}
                    className={fieldClass}
                  >
                    {["low", "medium", "high", "event_risk"].map((v) => (
                      <option key={v} value={v}>
                        {v}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="space-y-1 col-span-2">
                  <span className="text-[10px] uppercase tracking-wide text-qa-muted font-semibold">
                    Связанная защита
                  </span>
                  <input
                    type="text"
                    value={hedgeAttachmentId}
                    onChange={(e) => mark(setHedgeAttachmentId)(e.target.value)}
                    className={fieldClass}
                    placeholder="UUID или пусто"
                  />
                </label>
                {!isOpen && (
                  <label className="space-y-1">
                    <span className="text-[10px] uppercase tracking-wide text-qa-muted font-semibold">
                      Size ($) exit_logic
                    </span>
                    <input
                      type="number"
                      step="100"
                      value={exitDraft.positionSizeUsd}
                      onChange={(e) => patchExit({ positionSizeUsd: e.target.value })}
                      className={fieldClass}
                    />
                  </label>
                )}
              </div>
            )}

            <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
              <label className="space-y-1">
                <span className="text-[10px] uppercase tracking-wide text-terminal-down/90 font-semibold">
                  Стоп-лосс
                </span>
                <input
                  type="number"
                  step="0.01"
                  value={exitDraft.stopLoss}
                  onChange={(e) => patchExit({ stopLoss: e.target.value })}
                  className={fieldClass}
                />
              </label>
              <label className="space-y-1">
                <span className="text-[10px] uppercase tracking-wide text-terminal-up/90 font-semibold">
                  Тейк-профит
                </span>
                <input
                  type="number"
                  step="0.01"
                  value={exitDraft.takeProfit}
                  onChange={(e) => patchExit({ takeProfit: e.target.value })}
                  className={fieldClass}
                />
              </label>
              <label className="space-y-1">
                <span className="text-[10px] uppercase tracking-wide text-terminal-accent/90 font-semibold">
                  Скользящий стоп, %
                </span>
                <input
                  type="number"
                  step="0.1"
                  min={0}
                  value={exitDraft.trailingPct}
                  onChange={(e) => patchExit({ trailingPct: e.target.value })}
                  className={fieldClass}
                />
              </label>
              <label className="space-y-1">
                <span className="text-[10px] uppercase tracking-wide text-terminal-accent/90 font-semibold">
                  Частичное закрытие, %
                </span>
                <input
                  type="number"
                  step="1"
                  min={0}
                  max={100}
                  value={exitDraft.partialClosePct}
                  onChange={(e) => patchExit({ partialClosePct: e.target.value })}
                  className={fieldClass}
                />
              </label>
              <label className="space-y-1">
                <span className="text-[10px] uppercase tracking-wide text-qa-muted font-semibold">
                  Duration (hours)
                </span>
                <input
                  type="number"
                  step="1"
                  min={0}
                  disabled={isOpen}
                  value={exitDraft.timeExitHours}
                  onChange={(e) => patchExit({ timeExitHours: e.target.value })}
                  className={clsx(fieldClass, isOpen && "opacity-60")}
                />
              </label>
            </div>

            <div className="flex flex-wrap items-center gap-2 pt-1">
              <button
                type="button"
                disabled={busy || !dirty}
                onClick={() => saveMutation.mutate()}
                className={clsx(
                  "inline-flex items-center justify-center gap-1.5 px-4 py-2 rounded-md text-xs font-bold",
                  "bg-qa-panel-secondary text-white border border-qa-border-strong hover:bg-[var(--qa-hover)] disabled:opacity-50",
                )}
              >
                {saveMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                Save DealIntent
              </button>
              {dirty && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={resetDrafts}
                  className={clsx(
                    "inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-md text-xs font-bold",
                    "bg-transparent text-qa-text border border-qa-border-strong hover:bg-[var(--qa-hover)] disabled:opacity-50",
                  )}
                >
                  <X size={12} />
                  Сбросить
                </button>
              )}
              {isPending && (
                <DealIntentActionBar
                  dealIntentId={intent.id}
                  label="Deal Intent · ожидает одобрения"
                  busy={busy}
                  onApprove={(id) => approveMutation.mutate(id)}
                  onReject={(id) => rejectMutation.mutate(id)}
                />
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
