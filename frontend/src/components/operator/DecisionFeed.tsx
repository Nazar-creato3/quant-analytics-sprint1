"use client";

import { useMemo, useState, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { maneuversApi } from "@/lib/api";
import { extractErrorMessage, isLlmUnavailableMessage, llmUnavailableUserMessage } from "@/lib/errors";
import { usePipelineRun } from "@/hooks";
import { toast } from "react-hot-toast";
import { clsx } from "clsx";
import { Play, Loader2 } from "lucide-react";
import { StatusDot } from "./StatusDot";
import { ReasonState } from "./ReasonState";
import { CockpitPanelHeader } from "./CockpitPanelHeader";
import type { ManeuverApprovalOptions } from "@/types";
import { formatPipelineManeuverToast, isTradeableManeuver, MANEUVER_APPROVED_TOAST } from "@/lib/maneuvers";
import {
  invalidatePendingApprovalQueries,
  optimisticallyRemovePendingManeuver,
  recoverManeuverActionError,
} from "@/lib/maneuver-actions";
import { confidenceFilterMessage } from "@/lib/confidence-filter";
import { ApprovalCard } from "./PendingApprovalsPanel";
import { useProductContext } from "@/contexts/ProductContext";
import { isMoexSymbol } from "@/lib/moex-symbols";

export function DecisionFeed({
  enabled = true,
  className,
}: {
  enabled?: boolean;
  className?: string;
}) {
  const queryClient = useQueryClient();
  const [reportsEnabled, setReportsEnabled] = useState(enabled);
  const [actionId, setActionId] = useState<string | null>(null);

  const { trigger, isRunning, lastError: pipelineLastError, elapsedSec, slowRun } = usePipelineRun({
    useOpsEndpoint: true,
    onComplete: (_reportId, stats) => {
      if (stats?.report) {
        toast.success(
          formatPipelineManeuverToast(
            stats.tradeable_count,
            stats.maneuver_slots,
            stats.pending_approval_count,
            stats.backfill_hint,
          ),
        );
      } else {
        toast.error("Отчёт не загрузился — нажмите «Подобрать манёвры» ещё раз или обновите страницу", {
          duration: 9000,
        });
      }
      queryClient.invalidateQueries({ queryKey: ["pending-approvals"] });
      queryClient.invalidateQueries({ queryKey: ["decision-feed-pending-maneuvers"] });
    },
    onError: (msg) => {
      toast.error(msg, { duration: 9000 });
    },
  });

  useEffect(() => {
    setReportsEnabled(enabled);
  }, [enabled]);

  const { data: pendingManeuversPage, isLoading } = useQuery({
    queryKey: ["decision-feed-pending-maneuvers"],
    queryFn: () =>
      maneuversApi.list({ status: "pending,pending_approval,awaiting_approval", page_size: 20 }),
    refetchInterval: 20_000,
    enabled: enabled && reportsEnabled,
  });

  const { mode } = useProductContext();
  // «Боевой»: real orders go only to Moscow Exchange brokers (T-Bank, Finam); foreign venues
  // are paper-only (lawyer decision L-04). Ideas on foreign tickers cannot be approved there.
  const pendingManeuvers = useMemo(
    () =>
      (pendingManeuversPage?.items ?? [])
        .filter(isTradeableManeuver)
        .filter((m) => mode !== "live" || isMoexSymbol(m.ticker)),
    [pendingManeuversPage, mode],
  );
  const confidenceMessage = confidenceFilterMessage(pendingManeuversPage?.meta);

  const invalidateAll = () => {
    invalidatePendingApprovalQueries(queryClient);
  };

  const approveMutation = useMutation({
    mutationFn: ({ id, options }: { id: string; options?: ManeuverApprovalOptions }) =>
      maneuversApi.approve(id, undefined, options),
    onMutate: ({ id }) => {
      setActionId(id);
      optimisticallyRemovePendingManeuver(queryClient, id);
    },
    onSettled: () => setActionId(null),
    onSuccess: () => {
      toast.success(MANEUVER_APPROVED_TOAST);
      invalidateAll();
    },
    onError: async (err, variables) => {
      const recovered = await recoverManeuverActionError(variables.id, "approve");
      if (recovered) {
        toast.success("Сделка уже одобрена");
        invalidateAll();
        return;
      }
      toast.error(extractErrorMessage(err, "Ошибка одобрения"), { duration: 7000 });
    },
  });

  const rejectMutation = useMutation({
    mutationFn: (id: string) => maneuversApi.reject(id),
    onMutate: (id) => {
      setActionId(id);
      optimisticallyRemovePendingManeuver(queryClient, id);
    },
    onSettled: () => setActionId(null),
    onSuccess: () => {
      toast.success("Отклонено");
      invalidateAll();
    },
    onError: async (err, id) => {
      const recovered = await recoverManeuverActionError(id, "reject");
      if (recovered) {
        toast.success("Сделка уже обработана");
        invalidateAll();
        return;
      }
      toast.error(extractErrorMessage(err, "Ошибка отклонения"));
    },
  });

  const analysisBlockedMessage = useMemo(() => {
    if (!pipelineLastError) return null;
    if (isLlmUnavailableMessage(pipelineLastError)) {
      return llmUnavailableUserMessage(
        pipelineLastError.toLowerCase().includes("key_limit") ? "key_limit" : null,
      );
    }
    return pipelineLastError;
  }, [pipelineLastError]);

  return (
    <div className={clsx("cockpit-panel flex flex-col overflow-hidden min-h-0", className)}>
      <CockpitPanelHeader
        title="Инвестиционные маневры"
        badge={pendingManeuvers.length ? `${pendingManeuvers.length} ждут` : undefined}
        href="/operator/decisions"
      />

      <div className="px-2 pt-2 shrink-0">
        <button
          type="button"
          onClick={() => trigger(undefined)}
          disabled={isRunning}
          className={clsx(
            "w-full flex items-center justify-center gap-1.5 py-2 rounded-md text-[11px] font-bold uppercase tracking-wide",
            "bg-terminal-accent text-terminal-bg border border-terminal-accent shadow-sm hover:bg-terminal-accent-dim",
            "disabled:opacity-50 disabled:cursor-not-allowed",
          )}
        >
          {isRunning ? (
            <>
              <Loader2 size={12} className="animate-spin" /> Подбираем манёвры…
              {slowRun ? ` ${elapsedSec}с` : ""}
                          </>
          ) : (
            <>
              <Play size={12} /> Подобрать манёвры
            </>
          )}
        </button>
        {/* 149-FZ art. 10.2-2: the user is told a recommendation technology is used. */}
        <p className="mt-1.5 text-[9px] text-qa-muted leading-snug px-1" data-testid="rec-tech-note">
          Расчёт по вашим настройкам, не инвестиционная рекомендация.{" "}
          <a href="/legal/recommendations" className="underline hover:text-qa-text">
            Как подбираем
          </a>
        </p>
        {isRunning && slowRun && !pipelineLastError && (
          <p className="mt-2 text-[10px] text-qa-muted leading-relaxed px-1">
            Расчёт по всем бумагам занимает до 3–5 минут. Страницу можно не обновлять.
          </p>
        )}
        {pipelineLastError && !isRunning && (
          <p className="mt-2 text-[10px] text-terminal-accent leading-relaxed px-1">
            {analysisBlockedMessage ?? pipelineLastError}
          </p>
        )}
      </div>

      <div className="flex-1 overflow-y-auto overflow-x-hidden p-2 space-y-2 min-h-0 min-w-0">
        {isLoading ? (
          <ReasonState code="loading" title="Загрузка ленты…" compact />
        ) : pendingManeuvers.length > 0 ? (
          pendingManeuvers.map((m) => (
            <ApprovalCard
              key={m.id}
              m={m}
              busy={actionId === m.id}
              onApprove={(id, options) => approveMutation.mutate({ id, options })}
              onReject={(id) => rejectMutation.mutate(id)}
            />
          ))
        ) : confidenceMessage ? (
          <div className="cockpit-feed-item alert-caution-panel">
            <div className="flex items-center justify-between gap-2 mb-0.5">
              <span className="text-[10px] text-terminal-accent uppercase tracking-wide">Сигнал</span>
              <StatusDot level="caution" />
            </div>
            <p className="text-xs font-semibold text-qa-text leading-tight">Нет подходящих сделок</p>
            <p className="text-[10px] text-qa-text-secondary mt-1 leading-relaxed">{confidenceMessage}</p>
          </div>
        ) : analysisBlockedMessage ? (
          <div className="cockpit-feed-item alert-caution-panel">
            <div className="flex items-center justify-between gap-2 mb-0.5">
              <span className="text-[10px] text-terminal-accent uppercase tracking-wide">Анализ</span>
              <StatusDot level="block" />
            </div>
            <p className="text-xs font-semibold text-qa-text leading-tight">Манёвры не подобраны</p>
            <p className="text-[10px] text-qa-text-secondary mt-1 leading-relaxed">{analysisBlockedMessage}</p>
          </div>
        ) : (
          <div className="cockpit-feed-item">
            <p className="text-xs font-semibold text-qa-text leading-tight">Нет маневров</p>
            <p className="text-[10px] text-qa-muted mt-0.5">
              Нажмите «Подобрать манёвры»: система проверит бумаги из избранного и предложит сделки
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
