"use client";

import { useCallback, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { robotApi } from "@/lib/api";
import type { OHLCVBar, RobotLevel, RobotPlan } from "@/types";
import { RobotShadowStrip } from "./RobotShadowStrip";

interface RobotPanelProps {
  ticker: string;
  plan: RobotPlan | null;
  className?: string;
  onChanged?: () => void;
  /** Shadow equity curve from last Shadow run (research overlay). */
  shadowEquity?: number[];
  onShadowEquity?: (equity: number[]) => void;
  bars?: OHLCVBar[] | undefined;
  /** Live mid for one-click plan create when no plan exists. */
  entryHint?: number | null;
}

const PAPER_ONLY = new Set(["trail", "partial", "add"]);

function liveBlocked(plan: RobotPlan | null, kind: string): boolean {
  if (!plan || plan.mode !== "live") return false;
  const caps = plan.capabilities;
  if (caps?.paper?.includes(kind)) return true;
  return PAPER_ONLY.has(kind);
}

function Sparkline({ values, className }: { values: number[]; className?: string }) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const w = 120;
  const h = 28;
  const pts = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * w;
      const y = h - ((v - min) / span) * (h - 2) - 1;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const up = values[values.length - 1] >= values[0];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className={clsx("inline-block", className)} width={w} height={h} aria-hidden>
      <polyline fill="none" stroke={up ? "#34D399" : "#F87171"} strokeWidth="1.5" points={pts} />
    </svg>
  );
}

/** Desk table: robot levels / fills / pause / cancel / equity / flatten request. */
export function RobotPanel({
  ticker,
  plan,
  className,
  onChanged,
  shadowEquity = [],
  onShadowEquity,
  bars,
  entryHint = null,
}: RobotPanelProps) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [levels, setLevels] = useState<RobotLevel[]>(plan?.levels ?? []);
  const [fills, setFills] = useState<
    Array<{ level_id: string; action: string; qty: number; price: number }>
  >([]);
  const [liveEquity, setLiveEquity] = useState<number[]>([]);
  const [flattenReason, setFlattenReason] = useState("");
  const [flattenMsg, setFlattenMsg] = useState<string | null>(null);

  const bumpBook = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ["robot-book", ticker] });
    void qc.invalidateQueries({ queryKey: ["ticker-book", ticker] });
    void qc.invalidateQueries({ queryKey: ["decision-feed-robot-plans"] });
    onChanged?.();
  }, [qc, ticker, onChanged]);

  const refresh = useCallback(async () => {
    if (!plan?.id) return;
    try {
      const data = await robotApi.planLevels(plan.id);
      setLevels((data.levels as RobotLevel[]) || []);
      setFills(
        (data.fills || []).map((f) => ({
          level_id: String(f.level_id),
          action: String(f.action),
          qty: Number(f.qty),
          price: Number(f.price),
        }))
      );
      const eq = await robotApi.equityCurve(plan.id, "live");
      const curve = (eq.curve || [])
        .map((p) => Number(p.equity))
        .filter((n) => Number.isFinite(n));
      setLiveEquity(curve);
    } catch {
      /* keep local — migration may lag */
    }
  }, [plan?.id]);

  useEffect(() => {
    setLevels(plan?.levels ?? []);
    void refresh();
  }, [plan?.id, plan?.levels, refresh]);

  useEffect(() => {
    if (!plan?.id || plan.status !== "active") return;
    const id = window.setInterval(() => {
      void refresh();
    }, 15_000);
    return () => window.clearInterval(id);
  }, [plan?.id, plan?.status, refresh]);

  const createPlan = async (planType: "grid" | "dca" | "custom") => {
    const entry = entryHint != null && entryHint > 0 ? entryHint : null;
    if (!entry) {
      setErr("Нет цены на графике — подождите котировку");
      return;
    }
    setBusy(planType);
    setErr(null);
    try {
      await robotApi.createTyped({
        ticker,
        entry,
        side: "long",
        mode: "paper",
        plan_type: planType,
        plan_params:
          planType === "grid"
            ? { levels: 5, spacing_pct: 1.0 }
            : planType === "dca"
              ? { steps: 4, step_pct: 2.0 }
              : {},
      });
      bumpBook();
      setOpen(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Не удалось создать план");
    } finally {
      setBusy(null);
    }
  };

  if (!plan) {
    return (
      <div className={clsx("border-b border-sky-500/30 bg-sky-500/5 shrink-0", className)}>
        <div className="flex items-center gap-2 px-3 py-1">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide rounded border border-sky-400/70 bg-sky-500/15 text-sky-300 hover:bg-sky-500/25"
          >
            Робот
          </button>
          {err ? <p className="text-[10px] text-rose-400 truncate">{err}</p> : null}
        </div>
        {open ? (
          <div className="px-3 pb-2 space-y-2">
            <p className="text-[11px] text-qa-muted">
              GRID, DCA или уровни на графике. Сначала бумажный план, live — отдельно.
            </p>
            <div className="flex flex-wrap items-center gap-1">
              <button
                type="button"
                disabled={!!busy || !entryHint}
                onClick={() => void createPlan("grid")}
                className="px-2 py-1 text-[10px] uppercase tracking-wide font-semibold rounded border border-sky-500/50 text-sky-300 hover:bg-sky-500/15 disabled:opacity-40"
              >
                {busy === "grid" ? "…" : "Сетка"}
              </button>
              <button
                type="button"
                disabled={!!busy || !entryHint}
                onClick={() => void createPlan("dca")}
                className="px-2 py-1 text-[10px] uppercase tracking-wide font-semibold rounded border border-sky-500/50 text-sky-300 hover:bg-sky-500/15 disabled:opacity-40"
              >
                {busy === "dca" ? "…" : "DCA"}
              </button>
              <button
                type="button"
                disabled={!!busy || !entryHint}
                onClick={() => void createPlan("custom")}
                className="px-2 py-1 text-[10px] uppercase tracking-wide font-semibold rounded border border-cockpit-border text-qa-muted hover:text-qa-text disabled:opacity-40"
              >
                {busy === "custom" ? "…" : "Уровни"}
              </button>
            </div>
            <RobotShadowStrip ticker={ticker} bars={bars} plan={plan} onEquity={onShadowEquity} />
          </div>
        ) : null}
      </div>
    );
  }

  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    setErr(null);
    try {
      await fn();
      await refresh();
      bumpBook();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setBusy(null);
    }
  };

  const requestFlatten = async () => {
    setBusy("flatten");
    setFlattenMsg(null);
    setErr(null);
    try {
      const log = await robotApi.requestFlatten({
        reason: flattenReason || "desk emergency flatten",
        plan_ids: [plan.id],
        required_approvals: 2,
      });
      setFlattenMsg(
        `Flatten запрос ${String(log.id || "").slice(0, 8)}… — нужно ${log.required_approvals ?? 2} approve`,
      );
      setFlattenReason("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Flatten failed");
    } finally {
      setBusy(null);
    }
  };

  const equity = shadowEquity.length > 1 ? shadowEquity : liveEquity;

  return (
    <div className={clsx("border-b border-sky-500/40 bg-sky-500/5", className)}>
      <div className="flex items-center gap-2 px-3 py-1">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide rounded border border-sky-400/70 bg-sky-500/15 text-sky-300 hover:bg-sky-500/25"
        >
          Робот
        </button>
        {plan.status === "active" ? (
          <span className="text-[10px] text-sky-300/80 uppercase tracking-wide">{plan.mode}</span>
        ) : null}
      </div>

      {open ? (
        <>
          <div className="flex items-center gap-2 px-3 pb-1.5 text-[11px] min-w-0">
            <span className="tabular-nums text-qa-text">{plan.side}</span>
            <span className="text-qa-muted truncate">{plan.status}</span>
            {fills.length > 0 ? (
              <span className="text-sky-300/90 tabular-nums">сделок {fills.length}</span>
            ) : null}
            {plan.mode === "live" ? (
              <span className="text-amber-400/90 shrink-0" title={plan.capabilities?.note || ""}>
                ⚠ live: entry/SL/TP
              </span>
            ) : null}
            {equity.length > 1 ? <Sparkline values={equity} className="ml-1 opacity-90" /> : null}
          </div>
          <div className="flex flex-wrap items-center gap-1 px-3 pb-1.5">
            <button
              type="button"
              disabled={!!busy}
              onClick={() => act("pause", () => robotApi.pausePlan(plan.id))}
              className="px-2 py-0.5 text-[10px] uppercase tracking-wide border border-cockpit-border text-qa-muted hover:text-qa-text"
            >
              Пауза
            </button>
            <button
              type="button"
              disabled={!!busy}
              onClick={() => act("cancel", () => robotApi.cancelPlan(plan.id))}
              className="px-2 py-0.5 text-[10px] uppercase tracking-wide border border-cockpit-border text-rose-400/80 hover:text-rose-300"
            >
              Отменить
            </button>
            <input
              value={flattenReason}
              onChange={(e) => setFlattenReason(e.target.value)}
              placeholder="reason flatten"
              className="ml-auto min-w-[8rem] flex-1 max-w-[14rem] bg-transparent border border-cockpit-border px-1.5 py-0.5 text-[10px] text-qa-text"
            />
            <button
              type="button"
              disabled={!!busy}
              onClick={() => void requestFlatten()}
              className="px-2 py-0.5 text-[10px] uppercase tracking-wide border border-amber-500/40 text-amber-400/90 hover:text-amber-300"
              title="Multi-sig: 2 staff approvals"
            >
              Flatten*
            </button>
          </div>

          {err ? <p className="px-3 pb-1 text-[10px] text-rose-400">{err}</p> : null}
          {flattenMsg ? <p className="px-3 pb-1 text-[10px] text-amber-400/90">{flattenMsg}</p> : null}

          <div className="overflow-x-auto max-h-40 overflow-y-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-left text-qa-muted border-t border-cockpit-border">
                  <th className="px-3 py-1 font-normal">Уровень</th>
                  <th className="px-2 py-1 font-normal">Тип</th>
                  <th className="px-2 py-1 font-normal">Статус</th>
                  <th className="px-2 py-1 font-normal tabular-nums">Цена</th>
                  <th className="px-2 py-1 font-normal">%</th>
                  <th className="px-2 py-1 font-normal" />
                </tr>
              </thead>
              <tbody>
                {levels.map((lv) => {
                  const id = String(lv.id || lv.kind);
                  const blocked = liveBlocked(plan, String(lv.kind));
                  return (
                    <tr key={id} className="border-t border-cockpit-border/60 text-qa-text/90">
                      <td className="px-3 py-1 tabular-nums">{id}</td>
                      <td className="px-2 py-1">
                        {lv.kind}
                        {blocked ? (
                          <span className="ml-1 text-amber-400" title="Paper-only in live">
                            ⚠
                          </span>
                        ) : null}
                      </td>
                      <td className="px-2 py-1">{lv.status || "—"}</td>
                      <td className="px-2 py-1 tabular-nums">
                        {lv.price != null ? Number(lv.price).toFixed(4) : "—"}
                      </td>
                      <td className="px-2 py-1 tabular-nums">{lv.size_pct ?? "—"}</td>
                      <td className="px-2 py-1 text-right">
                        {lv.status === "watching" || lv.status === "pending" || lv.status === "armed" ? (
                          <button
                            type="button"
                            disabled={!!busy}
                            onClick={() => act(`p-${id}`, () => robotApi.pauseLevel(plan.id, id))}
                            className="text-[10px] text-qa-muted hover:text-qa-text"
                          >
                            Пауза
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {fills.length > 0 ? (
            <div className="px-3 py-1.5 border-t border-cockpit-border text-[10px] text-qa-muted">
              Fills:{" "}
              {fills
                .slice(-8)
                .map((f) => `${f.action}@${Number(f.price).toFixed(2)}×${Number(f.qty).toFixed(4)}`)
                .join(" · ")}
            </div>
          ) : null}
          <RobotShadowStrip ticker={ticker} bars={bars} plan={plan} onEquity={onShadowEquity} />
        </>
      ) : null}
    </div>
  );
}
