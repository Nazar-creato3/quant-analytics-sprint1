"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { X, ExternalLink, Loader2 } from "lucide-react";
import { toast } from "react-hot-toast";
import { maneuversApi } from "@/lib/api";
import { extractErrorMessage } from "@/lib/errors";
import { MANEUVER_APPROVED_TOAST, MANEUVER_CANCEL_QUERY_KEYS } from "@/lib/maneuvers";
import { formatExpectedPnlRange, formatTpHitProbability, formatUsdPnl } from "@/lib/profit-projection";
import { formatInstrumentPrice } from "@/lib/instrument-price-format";
import { classifySymbol } from "@/lib/asset-class";
import { fmtPrice } from "@/lib/formatPrice";
import type { Maneuver, ManeuverApprovalOptions } from "@/types";
import { isPendingApproval } from "@/lib/approval";
import { ManeuverActionBar } from "./ManeuverActionBar";
import { bookLabelRu, directionLabelRu, positionTruthRu, statusLabelRu, strategyLabelRu } from "@/lib/human-ru";

function formatPnl(value: number | null | undefined): string {
  if (value == null) return "—";
  return formatUsdPnl(value);
}

function entryPriceLabel(m: Maneuver): string {
  const price = m.fill_price ?? m.entry_zone_high;
  return formatInstrumentPrice(m.ticker, price);
}

function positionSizeLabel(m: Maneuver): string {
  if (!Number.isFinite(m.position_size_usd)) return "—";
  const currency = classifySymbol(m.ticker).currency;
  return fmtPrice(m.position_size_usd, currency, 0);
}

export function PositionDetailModal({
  maneuver,
  onClose,
}: {
  maneuver: Maneuver;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [actionId, setActionId] = useState<string | null>(null);
  const [slDraft, setSlDraft] = useState(maneuver.stop_loss?.toString() ?? "");
  const [tpDraft, setTpDraft] = useState(maneuver.take_profit?.toString() ?? "");

  const invalidate = () => {
    for (const key of MANEUVER_CANCEL_QUERY_KEYS) {
      queryClient.invalidateQueries({ queryKey: [key] });
    }
  };

  const approveMutation = useMutation({
    mutationFn: ({ id, options }: { id: string; options?: ManeuverApprovalOptions }) =>
      maneuversApi.approve(id, "Подтверждено из карточки позиции", options),
    onMutate: ({ id }) => setActionId(id),
    onSettled: () => setActionId(null),
    onSuccess: () => {
      toast.success(MANEUVER_APPROVED_TOAST);
      invalidate();
      onClose();
    },
    onError: err => toast.error(extractErrorMessage(err, "Ошибка одобрения")),
  });

  const rejectMutation = useMutation({
    mutationFn: (id: string) => maneuversApi.reject(id),
    onMutate: id => setActionId(id),
    onSettled: () => setActionId(null),
    onSuccess: () => {
      toast.success("Отклонено");
      invalidate();
      onClose();
    },
    onError: err => toast.error(extractErrorMessage(err, "Ошибка отклонения")),
  });

  const cancelMutation = useMutation({
    mutationFn: (id: string) => maneuversApi.cancel(id),
    onMutate: id => setActionId(id),
    onSettled: () => setActionId(null),
    onSuccess: result => {
      toast.success(result.message || "Позиция закрыта");
      invalidate();
      onClose();
    },
    onError: err => toast.error(extractErrorMessage(err, "Не удалось закрыть")),
  });

  const saveMutation = useMutation({
    mutationFn: () =>
      maneuversApi.edit(maneuver.id, {
        stop_loss: slDraft ? parseFloat(slDraft) : undefined,
        take_profit: tpDraft ? parseFloat(tpDraft) : undefined,
        note: "Изменено из карточки позиции",
      }),
    onSuccess: () => {
      toast.success("Стоп и цель сохранены");
      invalidate();
    },
    onError: err => toast.error(extractErrorMessage(err, "Не удалось сохранить")),
  });

  const busy = approveMutation.isPending || rejectMutation.isPending || cancelMutation.isPending || saveMutation.isPending;
  const unrealized = maneuver.unrealized_pnl ?? null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <button type="button" className="absolute inset-0 bg-black/75" aria-label="Закрыть" onClick={onClose} />
      <div className="relative w-full max-w-lg rounded-lg border border-cockpit-border-strong bg-cockpit-panel overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-cockpit-border bg-cockpit-panel-raised">
          <div>
            <h2 className="text-base font-bold text-white font-mono">{maneuver.ticker}</h2>
            <p className="text-[11px] text-qa-muted mt-0.5">
              {strategyLabelRu(maneuver.strategy_type)} · {directionLabelRu(maneuver.direction)} · {statusLabelRu(maneuver.status)}
            </p>
          </div>
          <button type="button" onClick={onClose} className="text-qa-muted hover:text-qa-text">
            <X size={18} />
          </button>
        </div>

        <div className="p-4 space-y-4 max-h-[70vh] overflow-y-auto">
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="cockpit-feed-item">
              <span className="text-[10px] uppercase text-qa-muted">Книга</span>
              <p className="text-sm font-semibold text-white mt-1">{bookLabelRu(maneuver.trading_mode)}</p>
              <p className="text-[10px] text-qa-muted mt-1">{positionTruthRu(maneuver)}</p>
            </div>
            <div className="cockpit-feed-item">
              <span className="text-[10px] uppercase text-qa-muted">Результат сейчас</span>
              <p className={clsx(
                "text-sm font-bold mt-1 tabular-nums",
                unrealized == null ? "text-qa-muted" : unrealized >= 0 ? "text-terminal-up" : "text-terminal-down",
              )}>
                {formatPnl(unrealized)}
              </p>
            </div>
            <div className="cockpit-feed-item">
              <span className="text-[10px] uppercase text-qa-muted">Вход</span>
              <p className="text-sm text-qa-text mt-1 tabular-nums">
                {entryPriceLabel(maneuver)}
              </p>
            </div>
            <div className="cockpit-feed-item">
              <span className="text-[10px] uppercase text-qa-muted">Размер</span>
              <p className="text-sm text-qa-text mt-1 tabular-nums">
                {positionSizeLabel(maneuver)}
              </p>
            </div>
            <div className="cockpit-feed-item">
              <span className="text-[10px] uppercase text-qa-muted">Ожидаемый результат</span>
              <p className="text-sm text-qa-text mt-1 tabular-nums">{formatExpectedPnlRange(maneuver)}</p>
            </div>
            <div className="cockpit-feed-item">
              <span className="text-[10px] uppercase text-qa-muted">Шанс дойти до цели до конца срока</span>
              <p className="text-sm text-qa-text mt-1 tabular-nums">{formatTpHitProbability(maneuver)}</p>
            </div>
            <div className="cockpit-feed-item">
              <span className="text-[10px] uppercase text-qa-muted">Если дойдём до цели</span>
              <p className="text-sm text-terminal-up/90 mt-1 tabular-nums">
                {maneuver.approx_profit != null ? formatPnl(maneuver.approx_profit) : "—"}
              </p>
            </div>
          </div>

          {maneuver.profit_disclosure && (
            <p className="text-[10px] text-qa-muted leading-relaxed border border-cockpit-border/60 rounded-md px-2 py-1.5">
              {maneuver.profit_disclosure}
            </p>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] uppercase text-terminal-down font-semibold">Защитный стоп</label>
              <input
                type="number"
                step="0.01"
                value={slDraft}
                onChange={e => setSlDraft(e.target.value)}
                className="input mt-1 text-xs tabular-nums"
                placeholder="—"
              />
            </div>
            <div>
              <label className="text-[10px] uppercase text-terminal-up font-semibold">Цель</label>
              <input
                type="number"
                step="0.01"
                value={tpDraft}
                onChange={e => setTpDraft(e.target.value)}
                className="input mt-1 text-xs tabular-nums"
                placeholder="—"
              />
            </div>
          </div>
          <button
            type="button"
            disabled={busy}
            onClick={() => saveMutation.mutate()}
            className="w-full py-2 rounded-md text-xs font-semibold bg-terminal-accent text-terminal-bg border border-terminal-accent hover:bg-terminal-accent-dim disabled:opacity-50"
          >
            Сохранить стоп и цель
          </button>

          {maneuver.rationale && (
            <div>
              <span className="text-[10px] uppercase text-qa-muted">Обоснование</span>
              <p className="text-xs text-qa-text mt-1 leading-relaxed">{maneuver.rationale}</p>
            </div>
          )}

          {isPendingApproval(maneuver.status) && (
            <div className="rounded-lg alert-caution-panel p-3">
              <p className="text-xs font-semibold text-terminal-accent mb-2">Требуется ваше решение</p>
              <ManeuverActionBar
                maneuverId={maneuver.id}
                ticker={maneuver.ticker}
                status={maneuver.status}
                busy={busy || actionId === maneuver.id}
                initialHorizon={maneuver.time_horizon}
                maneuver={maneuver}
                onApprove={(id, options) => approveMutation.mutate({ id, options })}
                onReject={id => rejectMutation.mutate(id)}
                onCancel={id => cancelMutation.mutate(id)}
              />
            </div>
          )}

          {!isPendingApproval(maneuver.status) && (
            <ManeuverActionBar
              maneuverId={maneuver.id}
              ticker={maneuver.ticker}
              status={maneuver.status}
              busy={busy || actionId === maneuver.id}
              initialHorizon={maneuver.time_horizon}
              maneuver={maneuver}
              onApprove={(id, options) => approveMutation.mutate({ id, options })}
              onReject={id => rejectMutation.mutate(id)}
              onCancel={id => cancelMutation.mutate(id)}
            />
          )}

          <Link
            href={`/cockpit/${encodeURIComponent(maneuver.ticker)}`}
            className="inline-flex items-center gap-1.5 text-xs text-terminal-accent hover:text-terminal-accent"
          >
            <ExternalLink size={12} />
            Открыть карточку бумаги
          </Link>
        </div>
      </div>
    </div>
  );
}
