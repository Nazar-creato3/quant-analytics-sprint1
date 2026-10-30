"use client";

import type { TerminalQuantFactor, TerminalQuantMetric } from "@/types/terminal";
import { EmptyHint, changeClass, fmtPct } from "../TermPanel";

export function QuantFactorsPanel({
  metrics,
  factors,
}: {
  metrics: TerminalQuantMetric[];
  factors?: TerminalQuantFactor[];
}) {
  const rows: TerminalQuantFactor[] =
    factors && factors.length
      ? factors
      : metrics.map((q) => ({
          id: q.id,
          name: q.label,
          weight: q.weight,
          contribution: q.contribution,
          value: q.value,
          source: q.source,
          freshness: q.freshness,
          confidence: q.confidence,
          tip: q.tip,
        }));

  if (!rows.length) {
    return (
      <EmptyHint text="Недостаточно данных для факторов." />
    );
  }

  const tip = rows.find((r) => r.tip)?.tip;

  return (
    <div>
      <div className="term-row grid-cols-[1.2fr_52px_56px_48px_1fr] text-terminal-muted text-[8px] uppercase sticky top-0 bg-terminal-panel">
        <span>Фактор</span>
        <span className="text-right">Вес</span>
        <span className="text-right">Вклад</span>
        <span className="text-right">Увер.</span>
        <span>Свежесть</span>
      </div>
      {rows.map((f) => (
        <div key={f.id} className="term-row !block space-y-0.5">
          <div className="grid grid-cols-[1.2fr_52px_56px_48px_1fr] gap-1 items-center">
            <div className="min-w-0">
              <p className="text-terminal-text truncate font-semibold">{f.name}</p>
              <p className="text-[10px] font-mono text-terminal-accent truncate">
                {f.value != null ? String(f.value) : "—"}
              </p>
            </div>
            <span className="text-right text-terminal-muted">
              {f.weight != null ? fmtPct(f.weight * (Math.abs(f.weight) <= 1.5 ? 100 : 1), 0) : "—"}
            </span>
            <span className={`text-right ${changeClass(f.contribution)}`}>
              {f.contribution != null ? f.contribution.toFixed(2) : "—"}
            </span>
            <span className="text-right text-terminal-muted">
              {f.confidence != null ? `${Math.round(f.confidence * 100)}%` : "—"}
            </span>
            <span className="text-[9px] text-terminal-muted truncate">
              {f.source ?? "—"}
              {f.freshness ? ` · ${f.freshness}` : ""}
            </span>
          </div>
          {f.tip ? (
            <p className="text-[9px] text-terminal-muted leading-snug pl-0.5">{f.tip}</p>
          ) : null}
        </div>
      ))}
      {tip ? (
        <div className="m-2 p-2 border border-terminal-border bg-terminal-surface">
          <p className="text-[8px] text-terminal-accent uppercase tracking-wider mb-0.5">
            Пояснение
          </p>
          <p className="text-[10px] text-terminal-text leading-snug">{tip}</p>
        </div>
      ) : null}
    </div>
  );
}
