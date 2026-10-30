"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { maneuversApi } from "@/lib/api";
import { extractErrorMessage } from "@/lib/errors";
import {
  invalidatePendingApprovalQueries,
  optimisticallyRemovePendingManeuver,
  recoverManeuverActionError,
} from "@/lib/maneuver-actions";
import { MANEUVER_APPROVED_TOAST } from "@/lib/maneuvers";
import { trimDisplayText } from "@/lib/text-display";
import type { Maneuver, ManeuverApprovalOptions } from "@/types";
import { toast } from "react-hot-toast";
import Link from "next/link";
import { Check, X, TrendingUp, TrendingDown } from "lucide-react";
import { clsx } from "clsx";
import { formatDurationPresets } from "@/lib/duration-i18n";
import { strategyLabelRu } from "@/lib/human-ru";
import { formatManeuverIncomeRange, isTradeableManeuver } from "@/lib/maneuvers";
import { confidenceFilterMessage } from "@/lib/confidence-filter";
import { Spinner } from "@/components/ui";
import { ManeuverIdeaButton } from "./ManeuverIdeaDialog";

const DURATION_PRESETS = formatDurationPresets("ru");

export function ApprovalCard({
  m,
  onApprove,
  onReject,
  busy,
}: {
  m: Maneuver;
  onApprove: (id: string, options?: ManeuverApprovalOptions) => void;
  onReject: (id: string) => void;
  busy: boolean;
}) {
  const retRange = formatManeuverIncomeRange(m);
  const [durationDraft, setDurationDraft] = useState(m.time_horizon || "7 дней");
  const [expiryDraft, setExpiryDraft] = useState("");

  return (
    <div className="cockpit-feed-item alert-caution-panel">
      <div className="flex items-center justify-between gap-2 mb-1">
        <div className="flex items-center gap-1.5">
          {m.direction === "long" ? (
            <TrendingUp size={12} className="text-terminal-up" />
          ) : (
            <TrendingDown size={12} className="text-terminal-down" />
          )}
          <span className="font-mono font-bold text-white text-sm">{m.ticker}</span>
          <span className="text-[10px] text-qa-muted">{strategyLabelRu(m.strategy_type)}</span>
        </div>
        <span className="text-[10px] text-terminal-accent font-semibold uppercase">Ожидает</span>
      </div>

      <p className="text-[11px] text-qa-muted line-clamp-2 mb-1.5">
        {m.rationale
          ? trimDisplayText(m.rationale, 120)
          : `Уверенность ${(m.confidence * 100).toFixed(0)}%`}
      </p>

      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-qa-muted mb-2">
        <span>уверенность {(m.confidence * 100).toFixed(0)}%</span>
        {retRange !== "—" && (
          <span className="text-terminal-up/80">ожидаемый доход {retRange}</span>
        )}
        {m.position_size_usd > 0 && (
          <span>${m.position_size_usd.toLocaleString("en", { maximumFractionDigits: 0 })}</span>
        )}
      </div>

      <div className="rounded-md border border-terminal-accent/25 bg-terminal-accent/5 p-1.5 mb-2">
        <div className="flex flex-wrap gap-1 mb-1">
          {DURATION_PRESETS.map((preset) => (
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

      <div className="flex gap-2">
        <ManeuverIdeaButton m={m} />
        <button
          onClick={() =>
            onApprove(m.id, {
              time_horizon: durationDraft.trim() || undefined,
              expiry_at: expiryDraft ? new Date(expiryDraft).toISOString() : undefined,
            })
          }
          disabled={busy}
          className={clsx(
            "flex-1 flex items-center justify-center gap-1 py-1.5 text-[11px] font-semibold btn-success-subtle",
            "disabled:opacity-40",
          )}
        >
          {busy ? <Spinner size={11} /> : <Check size={12} />}
          Одобрить
        </button>
        <button
          onClick={() => onReject(m.id)}
          disabled={busy}
          className={clsx(
            "flex-1 flex items-center justify-center gap-1 py-1.5 text-[11px] font-semibold btn-danger-subtle",
            "disabled:opacity-40",
          )}
        >
          {busy ? <Spinner size={11} /> : <X size={12} />}
          Отклонить
        </button>
        <Link
          href={`/cockpit/${encodeURIComponent(m.ticker)}`}
          className="px-2 py-1.5 rounded text-[11px] font-semibold text-terminal-accent border border-terminal-accent/40 hover:bg-[var(--qa-active)] whitespace-nowrap"
        >
          Карточка
        </Link>
      </div>
    </div>
  );
}

export function PendingApprovalsPanel({ enabled = true }: { enabled?: boolean }) {
  const queryClient = useQueryClient();
  const [busyId, setBusyId] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["pending-approvals"],
    queryFn: () => maneuversApi.list({ status: "pending,pending_approval,awaiting_approval", page_size: 20 }),
    refetchInterval: 15_000,
    enabled,
  });

  const pending = (data?.items ?? []).filter(isTradeableManeuver);
  const confidenceMessage = confidenceFilterMessage(data?.meta);

  const approveMutation = useMutation({
    mutationFn: ({ id, options }: { id: string; options?: ManeuverApprovalOptions }) =>
      maneuversApi.approve(id, undefined, options),
    onMutate: async ({ id }) => {
      setBusyId(id);
      await queryClient.cancelQueries({ queryKey: ["pending-approvals"] });
      const prev = optimisticallyRemovePendingManeuver(queryClient, id);
      return { prev };
    },
    onSuccess: () => {
      toast.success(MANEUVER_APPROVED_TOAST);
      invalidatePendingApprovalQueries(queryClient);
    },
    onError: async (err, variables, ctx) => {
      const id = variables.id;
      const recovered = await recoverManeuverActionError(id, "approve");
      if (recovered) {
        toast.success("Сделка уже одобрена");
        invalidatePendingApprovalQueries(queryClient);
        return;
      }
      if (ctx?.prev) {
        queryClient.setQueryData(["pending-approvals"], ctx.prev);
      }
      toast.error(extractErrorMessage(err, "Не удалось одобрить маневр"), {
        duration: 7000,
      });
    },
    onSettled: () => setBusyId(null),
  });

  const rejectMutation = useMutation({
    mutationFn: (id: string) => maneuversApi.reject(id),
    onMutate: async (id) => {
      setBusyId(id);
      await queryClient.cancelQueries({ queryKey: ["pending-approvals"] });
      const prev = optimisticallyRemovePendingManeuver(queryClient, id);
      return { prev };
    },
    onSuccess: () => {
      toast.success("Сделка отклонена");
      invalidatePendingApprovalQueries(queryClient);
    },
    onError: async (err, id, ctx) => {
      const recovered = await recoverManeuverActionError(id, "reject");
      if (recovered) {
        toast.success("Сделка уже обработана");
        invalidatePendingApprovalQueries(queryClient);
        return;
      }
      if (ctx?.prev) {
        queryClient.setQueryData(["pending-approvals"], ctx.prev);
      }
      toast.error(extractErrorMessage(err, "Не удалось отклонить маневр"));
    },
    onSettled: () => setBusyId(null),
  });

  if (!enabled || isLoading) return null;
  if (pending.length === 0 && !confidenceMessage) return null;

  return (
    <div className="cockpit-panel shrink-0 border border-terminal-accent/30">
      <div className="px-3 py-2 border-b border-cockpit-border flex items-center justify-between">
        <span className="text-[11px] font-semibold text-terminal-accent uppercase tracking-wide">
          Требуется ваше решение
        </span>
        {pending.length > 0 && (
          <span className="text-[10px] text-terminal-accent tabular-nums">{pending.length}</span>
        )}
      </div>
      <div className="p-2 space-y-2 max-h-48 overflow-y-auto">
        {confidenceMessage && pending.length === 0 ? (
          <div className="cockpit-feed-item alert-caution-panel">
            <p className="text-[11px] text-qa-text leading-relaxed">{confidenceMessage}</p>
            <Link
              href="/settings"
              className="inline-block mt-2 text-[10px] font-semibold text-terminal-accent hover:text-terminal-accent"
            >
              Изменить порог в настройках →
            </Link>
          </div>
        ) : (
          <>
            {pending.slice(0, 3).map(m => (
              <ApprovalCard
                key={m.id}
                m={m}
                busy={busyId === m.id}
                onApprove={(id, options) => approveMutation.mutate({ id, options })}
                onReject={id => rejectMutation.mutate(id)}
              />
            ))}
            {pending.length > 3 && (
              <p className="text-[10px] text-qa-muted text-center">
                +{pending.length - 3} ещё в ленте решений
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
