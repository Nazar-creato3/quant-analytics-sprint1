"use client";

import { PortfolioRiskProfileView } from "@/components/portfolio/PortfolioRiskProfileView";
import { useTickerForecast } from "@/hooks/useTickerForecast";
import { pct } from "@/lib/forecast-hierarchy";
import { changeClass, fmtNum, fmtPct, ruLabel } from "../TermPanel";

const METRIC_RU: Record<string, string> = {
  composite_risk_score: "Общий риск",
  tail_risk_score: "Риск резкого падения",
  liquidity_risk_score: "Риск ликвидности",
  volatility_expansion_probability: "Рост волатильности",
  event_impact_score: "Влияние событий",
  correlation_shift_score: "Смена корреляций",
};

const FLAG_RU: Record<string, string> = {
  tail_risk: "риск резкого падения",
  vol_expansion: "рост волатильности",
  liquidity_drought: "мало ликвидности",
  liquidity_deterioration_score: "ликвидность ухудшается",
  correlation_cluster: "бумаги двигаются вместе",
  event_impact_score: "важные события",
};
import type { TerminalRiskSummary } from "@/types/terminal";

function PortfolioRiskBlock({ risk }: { risk: TerminalRiskSummary }) {
  return (
    <div className="p-2 space-y-2 border-b border-terminal-border">
      <div className="flex items-end justify-between">
        <div>
          <p className="text-[9px] text-terminal-muted uppercase">Риск портфеля, баллы</p>
          <p className="text-lg font-bold text-terminal-text">
            {risk.score == null ? "—" : risk.score}
          </p>
          <p className="text-[10px] text-terminal-accent">{ruLabel(risk.label)}</p>
        </div>
        {risk.var_pct != null && (
          <p className="text-[10px] font-mono text-terminal-muted">VaR {fmtPct(risk.var_pct, 1)}</p>
        )}
      </div>
      {risk.score != null ? (
        <div className="term-gauge-track">
          <div className="term-gauge-fill" style={{ width: `${Math.min(100, risk.score)}%` }} />
        </div>
      ) : (
        <p className="text-[9px] text-terminal-muted">Оценка риска недоступна.</p>
      )}
      <div>
        {risk.high_beta.map((r) => (
          <div key={r.symbol} className="term-row grid-cols-[1fr_52px_40px_52px]">
            <span>
              {r.symbol}
              {r.note ? <span className="block text-[9px] text-terminal-muted">{r.note}</span> : null}
            </span>
            <span className="text-right font-mono text-terminal-text">
              {r.price != null ? fmtNum(r.price) : "—"}
            </span>
            <span className="text-terminal-muted text-right">
              {r.beta != null ? r.beta.toFixed(1) : "—"}
            </span>
            <span className={`text-right ${changeClass(r.change_pct)}`}>{fmtPct(r.change_pct)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function TickerRiskFromForecast({ symbol }: { symbol: string }) {
  const { hierarchyView, isLoading } = useTickerForecast(symbol);
  const risk = hierarchyView?.risk_forecast;

  if (isLoading && !risk) {
    return <p className="p-3 text-[11px] text-terminal-muted">Загрузка риска по {symbol}…</p>;
  }
  if (!risk) {
    return <p className="p-3 text-[11px] text-terminal-muted">Риск по {symbol} ещё считается</p>;
  }

  const metrics = Object.entries(risk.metrics ?? {}).filter(([k, v]) => v != null && METRIC_RU[k]);

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <p className="text-[9px] uppercase text-terminal-muted">Риск бумаги · {symbol}</p>
          <p className="text-lg font-bold font-mono">
            {risk.composite_risk_score != null ? risk.composite_risk_score.toFixed(1) : "—"}
          </p>
        </div>
        <div className="text-right text-[10px] font-mono text-terminal-muted">
          {risk.marginal_delta_var != null && <p>ΔVaR {pct(risk.marginal_delta_var)}</p>}
          {risk.marginal_delta_es != null && <p>ΔES {pct(risk.marginal_delta_es)}</p>}
        </div>
      </div>
      {risk.risk_flags && risk.risk_flags.length > 0 && (
        <ul className="flex flex-wrap gap-1">
          {risk.risk_flags.filter((flag) => FLAG_RU[flag]).map((flag) => (
            <li
              key={flag}
              className="text-[9px] uppercase border border-terminal-down/40 text-terminal-down px-1.5 py-0.5"
            >
              {FLAG_RU[flag]}
            </li>
          ))}
        </ul>
      )}
      {hierarchyView?.risk_engine_summary?.length ? (
        <ul className="text-[11px] text-terminal-text space-y-1 list-disc pl-4">
          {hierarchyView.risk_engine_summary.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
      {metrics.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
          {metrics.map(([key, value]) => (
            <div key={key} className="border border-terminal-border px-2 py-1.5">
              <p className="text-[8px] uppercase text-terminal-muted truncate">{METRIC_RU[key]}</p>
              <p className="text-[12px] font-mono text-terminal-text">
                {typeof value === "number" ? `${Math.round(value * 100)}%` : String(value)}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Full Risk desk: existing portfolio block + ticker forecast risk + portfolio analytics. */
export function TerminalRiskDesk({
  symbol,
  portfolioRisk,
}: {
  symbol: string;
  portfolioRisk: TerminalRiskSummary;
}) {
  return (
    <div className="space-y-3">
      <PortfolioRiskBlock risk={portfolioRisk} />
      <TickerRiskFromForecast symbol={symbol} />
      <div className="px-1 pb-2">
        <PortfolioRiskProfileView />
      </div>
    </div>
  );
}
