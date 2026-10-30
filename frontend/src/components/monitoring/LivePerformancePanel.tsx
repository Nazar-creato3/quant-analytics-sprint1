"use client";

import { useQuery } from "@tanstack/react-query";
import { signalMonitoringApi } from "@/lib/api";

export function LivePerformancePanel() {
  const { data, isLoading } = useQuery({
    queryKey: ["live-performance"],
    queryFn: () => signalMonitoringApi.livePerformance(),
    refetchInterval: 60_000,
  });

  const { data: drift } = useQuery({
    queryKey: ["model-drift"],
    queryFn: () => signalMonitoringApi.modelDrift(),
    refetchInterval: 120_000,
  });

  if (isLoading && !data) {
    return (
      <div className="rounded-lg border border-qa-border bg-qa-panel p-3 text-xs text-qa-muted">
        Loading live performance…
      </div>
    );
  }

  const fmtPct = (v: number | null | undefined) =>
    v != null ? `${(v * 100).toFixed(1)}%` : "—";
  const fmtNum = (v: number | null | undefined) => (v != null ? v.toFixed(2) : "—");

  return (
    <div className="rounded-lg border border-qa-border bg-qa-panel p-3 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-qa-text">Точность сигналов в работе</h3>
        <span className="text-[10px] uppercase tracking-wide text-terminal-accent">LIVE</span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
        <Metric label="Sharpe (live)" value={fmtNum(data?.sharpe_ratio)} />
        <Metric label="Win rate (live)" value={fmtPct(data?.win_rate)} />
        <Metric label="Expectancy" value={data?.expectancy_usd != null ? `$${data.expectancy_usd}` : "—"} />
        <Metric label="Max DD (live)" value={data?.max_drawdown_pct != null ? `${data.max_drawdown_pct}%` : "—"} />
      </div>
      <div className="grid grid-cols-2 gap-2 text-[11px] text-qa-muted border-t border-qa-border pt-2">
        <div>
          <span className="uppercase text-[10px]">Backtest (labeled)</span>
          <div>
            Sharpe {fmtNum(data?.backtest_sharpe)} · WR {fmtPct(data?.backtest_win_rate)}
          </div>
        </div>
        <div>
          <span className="uppercase text-[10px]">Выборка</span>
          <div>{data?.sample_size ?? 0} closed maneuvers</div>
        </div>
      </div>
      {drift?.alert && (
        <div className="text-[11px] text-qa-warning border border-qa-accent-border rounded p-2 bg-qa-active">
          {drift.alert_message}
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-qa-panel-secondary rounded p-2 border border-qa-border">
      <div className="text-[10px] text-qa-muted uppercase">{label}</div>
      <div className="text-sm font-semibold text-qa-text">{value}</div>
    </div>
  );
}
