"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "react-hot-toast";
import { LineChart, Play } from "lucide-react";
import { strategyComposerApi } from "@/lib/api";
import type { ComposerBacktestResult, ComposerConfig } from "@/types";
import { Spinner } from "@/components/ui";

export function ComposerBacktestPanel({ config }: { config: ComposerConfig }) {
  const [symbol, setSymbol] = useState("SPY");
  const [lookbackDays, setLookbackDays] = useState("504");
  const [result, setResult] = useState<ComposerBacktestResult | null>(null);

  const run = useMutation({
    mutationFn: () =>
      strategyComposerApi.backtest({
        config,
        symbol: symbol.trim().toUpperCase(),
        lookback_days: Number(lookbackDays),
      }),
    onSuccess: (data) => {
      setResult(data);
      toast.success("Backtest завершён");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <div className="cockpit-panel p-3 space-y-3">
      <div className="cockpit-panel-header flex items-center gap-2">
        <LineChart size={14} />
        Проверка на истории (скользящее окно без заглядывания вперёд)
      </div>
      <div className="grid grid-cols-2 gap-2">
        <input className="cockpit-input text-xs" value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="Symbol" />
        <input className="cockpit-input text-xs" value={lookbackDays} onChange={(e) => setLookbackDays(e.target.value)} placeholder="Lookback days" />
      </div>
      <button type="button" className="cockpit-action-btn text-terminal-accent w-full" disabled={run.isPending} onClick={() => run.mutate()}>
        {run.isPending ? <Spinner size={12} /> : <Play size={12} />}
        Запустить backtest
      </button>
      {result && (
        <div className="text-[11px] font-mono space-y-1 text-qa-muted">
          <div>return: {result.total_return != null ? (result.total_return * 100).toFixed(2) + "%" : "—"}</div>
          <div>max DD: {result.max_drawdown != null ? (result.max_drawdown * 100).toFixed(2) + "%" : "—"}</div>
          <div>purged CV win: {result.purged_cv_win_rate != null ? (result.purged_cv_win_rate * 100).toFixed(1) + "%" : "—"}</div>
          <div>folds: {result.purged_folds}</div>
          {result.insufficient_data && <div className="text-terminal-down">Недостаточно данных</div>}
          {(result.notes || []).slice(0, 3).map((n) => (
            <div key={n}>{n}</div>
          ))}
        </div>
      )}
    </div>
  );
}
