"use client";

import { useState } from "react";
import { clsx } from "clsx";
import { robotApi } from "@/lib/api";
import type { OHLCVBar, RobotPlan } from "@/types";

interface RobotShadowStripProps {
  ticker: string;
  bars: OHLCVBar[] | undefined;
  plan: RobotPlan | null;
  className?: string;
  onEquity?: (equity: number[]) => void;
}

type ShadowResult = {
  total_return?: number;
  max_drawdown?: number;
  exit_reason?: string | null;
  n_fills?: number;
  realized_pnl?: number;
  equity_end?: number;
  avg_slippage?: number;
  avg_latency_bars?: number;
  equity_curve?: number[];
};

function humanExit(reason: string | null | undefined): string | null {
  if (!reason) return null;
  const key = reason.trim().toLowerCase();
  const map: Record<string, string> = {
    kill_switch: "сработало ограничение просадки",
    stop: "выход по стопу",
    take_profit: "выход по тейку",
    take_profit_partial: "частичный тейк",
    end_of_bars: "конец окна на графике",
    flat: "без позиции",
  };
  return map[key] ?? reason.replace(/_/g, " ");
}

/** Compact desk control: replay RobotPlan on visible OHLC bars. */
export function RobotShadowStrip({
  ticker,
  bars,
  plan,
  className,
  onEquity,
}: RobotShadowStripProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<ShadowResult | null>(null);

  const barCount = Math.min(bars?.length ?? 0, 500);
  const canRun = !!ticker && (bars?.length ?? 0) >= 8;

  const closeStrip = () => {
    setOpen(false);
    setErr(null);
    setResult(null);
    onEquity?.([]);
  };

  const run = async () => {
    if (!canRun || !bars) return;
    // Second click closes the strip so the chart keeps full height.
    if (open) {
      closeStrip();
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const slice = bars.slice(-barCount);
      const ohlc = slice.map((b) => ({
        high: Number(b.high),
        low: Number(b.low),
        close: Number(b.close),
      }));
      const entry =
        plan?.levels?.find((l) => l.kind === "entry" && typeof l.price === "number")?.price ??
        ohlc[0]?.close;
      const body =
        plan?.levels && plan.levels.length > 0
          ? {
              levels: plan.levels as unknown as Array<Record<string, unknown>>,
              bars: ohlc,
              side: plan.side || "long",
              qty: 1,
              kill_switch_pct: plan.kill_switch_pct ?? 5,
              slippage_pct: 0.0005,
              latency_bars: 0,
            }
          : {
              bars: ohlc,
              entry: Number(entry),
              side: "long",
              use_apex_defaults: true,
              qty: 1,
              kill_switch_pct: 5,
              slippage_pct: 0.0005,
            };
      const data = await robotApi.shadow(body);
      const typed = data as ShadowResult;
      setResult(typed);
      const curve = Array.isArray(typed.equity_curve)
        ? typed.equity_curve.filter((n): n is number => typeof n === "number" && Number.isFinite(n))
        : [];
      onEquity?.(curve);
      setOpen(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Прогон по истории не выполнился");
      setResult(null);
      onEquity?.([]);
      setOpen(true);
    } finally {
      setBusy(false);
    }
  };

  const retPct =
    typeof result?.total_return === "number" ? result.total_return * 100 : null;
  const ddPct =
    typeof result?.max_drawdown === "number" ? result.max_drawdown * 100 : null;
  const exitLabel = humanExit(result?.exit_reason);
  const fills = result?.n_fills;
  const slipPct =
    typeof result?.avg_slippage === "number" && result.avg_slippage > 0
      ? result.avg_slippage * 100
      : null;

  return (
    <div className={clsx("border-b border-cockpit-border text-[11px] shrink-0", className)}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-1.5">
        <button
          type="button"
          disabled={!canRun || busy}
          onClick={() => void run()}
          title={
            open
              ? "Скрыть результат прогона и вернуть высоту графика"
              : "Прогнать текущий план робота по видимым барам графика (без реальных ордеров)"
          }
          aria-pressed={open}
          className={clsx(
            "uppercase tracking-wide text-[9px] font-semibold px-2 py-0.5 rounded border",
            busy
              ? "border-qa-border text-qa-muted"
              : open
                ? "border-sky-400 text-sky-300 bg-sky-500/10"
                : "border-sky-500/40 text-sky-400 hover:border-sky-400/70",
          )}
        >
          {busy ? "Считаем…" : open ? "Shadow · скрыть" : "Shadow"}
        </button>
        {!open ? (
          <span className="text-qa-muted leading-snug">
            {canRun
              ? `Бумажный прогон плана · до ${barCount} баров · проскальзывание ~0.05%`
              : "Нужно больше баров на графике, чтобы прогнать план"}
          </span>
        ) : null}
        {open && result && !err ? (
          <span className="tabular-nums text-qa-text leading-snug truncate max-w-[min(100%,720px)]">
            <span className="text-qa-muted">Итог </span>
            <span
              className={clsx(
                (retPct ?? 0) >= 0 ? "text-terminal-up" : "text-terminal-down",
              )}
            >
              {retPct != null ? `${retPct >= 0 ? "+" : ""}${retPct.toFixed(2)}%` : "—"}
            </span>
            <span className="text-qa-muted"> · просадка </span>
            {ddPct != null ? `${ddPct.toFixed(2)}%` : "—"}
            {exitLabel ? <span className="text-qa-muted"> · {exitLabel}</span> : null}
            {fills != null ? <span className="text-qa-muted"> · сделок {fills}</span> : null}
            {slipPct != null ? (
              <span className="text-qa-muted"> · slip {slipPct.toFixed(3)}%</span>
            ) : null}
          </span>
        ) : null}
        {open && err ? <span className="text-terminal-down">{err}</span> : null}
      </div>
    </div>
  );
}
