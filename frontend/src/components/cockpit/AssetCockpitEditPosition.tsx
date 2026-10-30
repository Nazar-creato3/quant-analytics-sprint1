"use client";

import { strategyLabelRu, statusLabelRu } from "@/lib/human-ru";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Loader2, Save, X } from "lucide-react";
import { toast } from "react-hot-toast";
import { maneuversApi } from "@/lib/api";
import { extractErrorMessage } from "@/lib/errors";
import { isPendingApproval } from "@/lib/approval";
import { MANEUVER_CANCEL_QUERY_KEYS, OPEN_POSITION_STATUS_FILTER } from "@/lib/maneuvers";
import type { Maneuver } from "@/types";
import { CockpitPanelHeader } from "@/components/operator/CockpitPanelHeader";
import { useEffect, useMemo, useState } from "react";

interface AssetCockpitEditPositionProps {
  symbol: string;
}

const fieldClass =
  "input text-xs font-mono tabular-nums py-2 px-2.5 rounded-md";

const HORIZON_PRESETS = [
  "1–3 дня",
  "1–5 дней",
  "3–10 дней",
  "1–2 недели",
  "2–4 недели",
  "4–12 недель",
] as const;

function horizonToDays(horizon: string | null | undefined): number | null {
  if (!horizon) return null;
  const text = horizon.replace(/[–—]/g, "-");
  const nums = [...text.matchAll(/\d+(?:\.\d+)?/g)].map((m) => parseFloat(m[0]));
  if (!nums.length) return null;
  const mid = nums.reduce((a, b) => a + b, 0) / nums.length;
  const lower = text.toLowerCase();
  if (/час|hour|h\b/.test(lower)) return mid / 24;
  if (/недел|week|w\b/.test(lower)) return mid * 7;
  if (/месяц|month|mo\b/.test(lower)) return mid * 30;
  return mid;
}

function entryRef(m: Maneuver): number | null {
  const v =
    m.fill_price ?? m.entry_zone_high ?? m.entry_zone_low ?? null;
  return v != null && Number.isFinite(v) && v > 0 ? Number(v) : null;
}

function directionSign(m: Maneuver): number {
  return String(m.direction).toLowerCase() === "short" ? -1 : 1;
}

/** Suggest scaled SL/TP when investment horizon changes (sqrt time). */
function scaledLevels(
  m: Maneuver,
  horizonDraft: string,
  entryDraft: number | null,
): { stopLoss: number | null; takeProfit: number | null; timeToCloseDays: number | null } {
  const entry = entryDraft ?? entryRef(m);
  const oldDays = horizonToDays(m.time_horizon) ?? 5;
  const newDays = horizonToDays(horizonDraft) ?? oldDays;
  const scale = Math.sqrt(Math.max(0.25, newDays) / Math.max(0.25, oldDays));
  const sign = directionSign(m);

  let stopLoss: number | null = m.stop_loss ?? null;
  let takeProfit: number | null = m.take_profit ?? null;

  if (entry != null && m.stop_loss != null) {
    const dist = Math.abs(entry - m.stop_loss);
    stopLoss = Number((entry - sign * dist * scale).toFixed(4));
  }
  if (entry != null && m.take_profit != null) {
    const dist = Math.abs(m.take_profit - entry);
    takeProfit = Number((entry + sign * dist * scale).toFixed(4));
  }

  return { stopLoss, takeProfit, timeToCloseDays: newDays };
}

/** Live metrics from current form drafts (before Save). */
function previewMetrics(
  m: Maneuver,
  entryDraft: number | null,
  sizeDraft: number | null,
  stopLoss: number | null,
  takeProfit: number | null,
  timeToCloseDays: number | null,
): {
  approxProfit: number | null;
  riskReward: number | null;
  riskUsd: number | null;
  timeToCloseDays: number | null;
} {
  const entry = entryDraft ?? entryRef(m);
  const size = sizeDraft ?? m.position_size_usd ?? 0;
  const sign = directionSign(m);
  let approxProfit: number | null = null;
  let riskUsd: number | null = null;
  let riskReward: number | null = null;

  if (entry != null && entry > 0 && size > 0) {
    const qty = size / entry;
    if (takeProfit != null) {
      approxProfit = Number(((takeProfit - entry) * qty * sign).toFixed(2));
    }
    if (stopLoss != null) {
      riskUsd = Number((Math.abs(entry - stopLoss) * qty).toFixed(2));
    }
    if (approxProfit != null && riskUsd != null && riskUsd > 0) {
      riskReward = Number((Math.abs(approxProfit) / riskUsd).toFixed(2));
    }
  }

  return { approxProfit, riskUsd, riskReward, timeToCloseDays };
}

export function AssetCockpitEditPosition({ symbol }: AssetCockpitEditPositionProps) {
  const queryClient = useQueryClient();
  const [entryDraft, setEntryDraft] = useState("");
  const [slDraft, setSlDraft] = useState("");
  const [tpDraft, setTpDraft] = useState("");
  const [sizeDraft, setSizeDraft] = useState("");
  const [horizonDraft, setHorizonDraft] = useState("");
  const [dirty, setDirty] = useState(false);

  const { data: pendingPage } = useQuery({
    queryKey: ["cockpit-pending-maneuver", symbol],
    queryFn: () =>
      maneuversApi.list({
        ticker: symbol,
        status: "pending,pending_approval,awaiting_approval",
        page_size: 5,
        skip_confidence_filter: true,
      }),
    refetchInterval: 20_000,
    enabled: !!symbol,
  });

  const { data: openPage } = useQuery({
    queryKey: ["cockpit-open-maneuver", symbol],
    queryFn: () =>
      maneuversApi.list({
        ticker: symbol,
        status: OPEN_POSITION_STATUS_FILTER,
        page_size: 5,
      }),
    refetchInterval: 20_000,
    enabled: !!symbol,
  });

  const pending: Maneuver | undefined = (pendingPage?.items ?? []).find(
    (m) => m.strategy_type !== "no_trade" && isPendingApproval(m.status),
  );
  const openPos: Maneuver | undefined = (openPage?.items ?? []).find(
    (m) => m.strategy_type !== "no_trade",
  );
  const maneuver = pending ?? openPos;
  const isPending = !!pending;
  const isOpen = !!maneuver && !isPending;

  useEffect(() => {
    if (!maneuver || dirty) return;
    const entry =
      maneuver.fill_price ?? maneuver.entry_zone_high ?? maneuver.entry_zone_low;
    setEntryDraft(entry?.toString() ?? "");
    setSlDraft(maneuver.stop_loss?.toString() ?? "");
    setTpDraft(maneuver.take_profit?.toString() ?? "");
    setSizeDraft(maneuver.position_size_usd?.toString() ?? "");
    setHorizonDraft(maneuver.time_horizon ?? HORIZON_PRESETS[1]);
  }, [maneuver, dirty]);

  const entryNum = entryDraft ? parseFloat(entryDraft) : null;
  const sizeNum = sizeDraft ? parseFloat(sizeDraft) : null;
  const slNum = slDraft ? parseFloat(slDraft) : null;
  const tpNum = tpDraft ? parseFloat(tpDraft) : null;

  // When horizon changes, push scaled SL/TP into drafts (live, before save).
  useEffect(() => {
    if (!maneuver || !dirty) return;
    const scaled = scaledLevels(
      maneuver,
      horizonDraft || maneuver.time_horizon,
      Number.isFinite(entryNum) ? entryNum : null,
    );
    if (scaled.stopLoss != null) setSlDraft(String(scaled.stopLoss));
    if (scaled.takeProfit != null) setTpDraft(String(scaled.takeProfit));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only re-scale on horizon change
  }, [horizonDraft]);

  const preview = useMemo(() => {
    if (!maneuver) return null;
    const days =
      horizonToDays(horizonDraft || maneuver.time_horizon) ??
      horizonToDays(maneuver.time_horizon) ??
      null;
    return previewMetrics(
      maneuver,
      Number.isFinite(entryNum) ? entryNum : null,
      Number.isFinite(sizeNum) ? sizeNum : null,
      Number.isFinite(slNum) ? slNum : maneuver.stop_loss ?? null,
      Number.isFinite(tpNum) ? tpNum : maneuver.take_profit ?? null,
      days,
    );
  }, [maneuver, horizonDraft, entryNum, sizeNum, slNum, tpNum]);

  const invalidate = () => {
    for (const key of MANEUVER_CANCEL_QUERY_KEYS) {
      queryClient.invalidateQueries({ queryKey: [key] });
    }
    queryClient.invalidateQueries({ queryKey: ["cockpit-pending-maneuver", symbol] });
    queryClient.invalidateQueries({ queryKey: ["cockpit-open-maneuver", symbol] });
    queryClient.invalidateQueries({ queryKey: ["asset-cockpit", symbol] });
    queryClient.invalidateQueries({ queryKey: ["bottom-positions"] });
  };

  const resetDrafts = () => {
    setDirty(false);
    if (!maneuver) return;
    const entry =
      maneuver.fill_price ?? maneuver.entry_zone_high ?? maneuver.entry_zone_low;
    setEntryDraft(entry?.toString() ?? "");
    setSlDraft(maneuver.stop_loss?.toString() ?? "");
    setTpDraft(maneuver.take_profit?.toString() ?? "");
    setSizeDraft(maneuver.position_size_usd?.toString() ?? "");
    setHorizonDraft(maneuver.time_horizon ?? HORIZON_PRESETS[1]);
  };

  const mark = <T,>(setter: (v: T) => void) => (v: T) => {
    setDirty(true);
    setter(v);
  };

  const saveMutation = useMutation({
    mutationFn: () => {
      if (!maneuver) throw new Error("No maneuver");
      const entry = parseFloat(entryDraft);
      const sl = slDraft ? parseFloat(slDraft) : undefined;
      const tp = tpDraft ? parseFloat(tpDraft) : undefined;
      const size = sizeDraft ? parseFloat(sizeDraft) : undefined;
      return maneuversApi.edit(maneuver.id, {
        entry_price: !isOpen && Number.isFinite(entry) ? entry : undefined,
        stop_loss: sl,
        take_profit: tp,
        size_usd: size,
        time_horizon: horizonDraft.trim() || undefined,
        note: "Edited in Asset Cockpit",
      });
    },
    onSuccess: () => {
      toast.success("Параметры сохранены");
      setDirty(false);
      invalidate();
    },
    onError: (err) => toast.error(extractErrorMessage(err, "Save failed")),
  });

  const approveMutation = useMutation({
    mutationFn: (id: string) =>
      maneuversApi.approve(id, "Approved from Cockpit after edit", {
        time_horizon: horizonDraft.trim() || maneuver?.time_horizon,
      }),
    onSuccess: () => {
      toast.success("Одобрено");
      setDirty(false);
      invalidate();
    },
    onError: (err) => toast.error(extractErrorMessage(err, "Approve failed")),
  });

  const rejectMutation = useMutation({
    mutationFn: (id: string) => maneuversApi.reject(id),
    onSuccess: () => {
      toast.success("Отклонено");
      setDirty(false);
      invalidate();
    },
    onError: (err) => toast.error(extractErrorMessage(err, "Reject failed")),
  });

  const busy = saveMutation.isPending || approveMutation.isPending || rejectMutation.isPending;
  const subtitle = isPending
    ? "Ожидает решения"
    : isOpen
      ? "Открытая позиция"
      : "Нет сделки";

  return (
    <div className="cockpit-panel overflow-hidden">
      <CockpitPanelHeader title="Edit Position" subtitle={subtitle} />
      <div className="p-4">
        {!maneuver ? (
          <p className="text-xs text-qa-muted leading-relaxed">
            По {symbol} нет pending-сигнала и нет открытой позиции. Запустите анализ рынка
            или выберите тикер с активной сделкой — тогда здесь появятся поля для правки.
          </p>
        ) : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2 text-[11px] pb-3 border-b border-cockpit-border/60">
              <span className="font-mono font-bold text-white">{maneuver.ticker}</span>
              <span className="px-1.5 py-0.5 rounded bg-[var(--qa-active)] text-terminal-accent border border-terminal-accent/40 uppercase text-[10px]">
                {strategyLabelRu(maneuver.strategy_type)}
              </span>
              <span className="px-1.5 py-0.5 rounded bg-[var(--qa-active)] text-terminal-accent border border-terminal-accent/40 uppercase text-[10px]">
                {statusLabelRu(maneuver.status)}
              </span>
              <span className="text-terminal-up tabular-nums ml-auto">
                conf {(maneuver.confidence * 100).toFixed(0)}%
              </span>
            </div>

            <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
              <label className="space-y-1">
                <span className="text-[10px] uppercase tracking-wide text-qa-muted font-semibold">
                  Вход
                </span>
                <input
                  type="number"
                  step="0.01"
                  value={entryDraft}
                  disabled={isOpen}
                  onChange={(e) => mark(setEntryDraft)(e.target.value)}
                  className={clsx(fieldClass, isOpen && "opacity-60")}
                />
              </label>
              <label className="space-y-1">
                <span className="text-[10px] uppercase tracking-wide text-terminal-down/90 font-semibold">
                  Стоп-лосс
                </span>
                <input
                  type="number"
                  step="0.01"
                  value={slDraft}
                  onChange={(e) => mark(setSlDraft)(e.target.value)}
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
                  value={tpDraft}
                  onChange={(e) => mark(setTpDraft)(e.target.value)}
                  className={fieldClass}
                />
              </label>
              <label className="space-y-1">
                <span className="text-[10px] uppercase tracking-wide text-qa-muted font-semibold">
                  Size ($)
                </span>
                <input
                  type="number"
                  step="100"
                  value={sizeDraft}
                  onChange={(e) => mark(setSizeDraft)(e.target.value)}
                  className={fieldClass}
                />
              </label>
              <label className="space-y-1">
                <span className="text-[10px] uppercase tracking-wide text-terminal-accent/90 font-semibold">
                  Срок вложений
                </span>
                <select
                  value={horizonDraft}
                  onChange={(e) => mark(setHorizonDraft)(e.target.value)}
                  className={fieldClass}
                >
                  {!HORIZON_PRESETS.includes(horizonDraft as (typeof HORIZON_PRESETS)[number]) &&
                    horizonDraft && (
                      <option value={horizonDraft}>{horizonDraft}</option>
                    )}
                  {HORIZON_PRESETS.map((h) => (
                    <option key={h} value={h}>
                      {h}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            {preview && (
              <div className="rounded-md border border-cockpit-border/70 bg-black/20 px-3 py-2 grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px]">
                <div>
                  <div className="text-qa-muted uppercase text-[9px]">P&amp;L при TP (полный)</div>
                  <div
                    className={clsx(
                      "font-mono tabular-nums font-semibold",
                      (preview.approxProfit ?? 0) >= 0 ? "text-terminal-up" : "text-terminal-down",
                    )}
                  >
                    {preview.approxProfit != null ? `$${preview.approxProfit}` : "—"}
                  </div>
                </div>
                <div>
                  <div className="text-qa-muted uppercase text-[9px]">Риск ($)</div>
                  <div className="font-mono tabular-nums text-terminal-accent">
                    {preview.riskUsd != null ? `$${preview.riskUsd}` : "—"}
                  </div>
                </div>
                <div>
                  <div className="text-qa-muted uppercase text-[9px]">R:R</div>
                  <div className="font-mono tabular-nums text-white">
                    {preview.riskReward != null ? preview.riskReward.toFixed(2) : "—"}
                  </div>
                </div>
                <div>
                  <div className="text-qa-muted uppercase text-[9px]">Горизонт (дней)</div>
                  <div className="font-mono tabular-nums text-terminal-accent">
                    {preview.timeToCloseDays != null
                      ? `~${preview.timeToCloseDays.toFixed(1)}`
                      : "—"}
                  </div>
                </div>
                {dirty && (
                  <p className="col-span-full text-[10px] text-qa-muted">
                    Предпросмотр до сохранения — можно выйти без Save, сделка не изменится.
                  </p>
                )}
              </div>
            )}

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
                Save
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
                <>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => approveMutation.mutate(maneuver.id)}
                    className={clsx(
                      "inline-flex items-center justify-center gap-1.5 px-4 py-2 rounded-md text-xs font-bold",
                      "btn-success disabled:opacity-50",
                    )}
                  >
                    {approveMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : null}
                    Approve
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => rejectMutation.mutate(maneuver.id)}
                    className={clsx(
                      "inline-flex items-center justify-center gap-1.5 px-4 py-2 rounded-md text-xs font-bold",
                      "btn-danger-solid disabled:opacity-50",
                    )}
                  >
                    {rejectMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : null}
                    Reject
                  </button>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
