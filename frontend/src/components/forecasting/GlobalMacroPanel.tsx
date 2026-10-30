"use client";

import { clsx } from "clsx";
import { Globe, Layers } from "lucide-react";

interface RegimeMapEntry {
  symbol: string;
  label: string;
  dominant_regime: string;
  dominant_regime_ru: string;
  confidence: number;
}

interface FactorRotationEntry {
  factor: string;
  score: number;
  rank: number;
  direction: string;
}

export interface GlobalMacroData {
  correlation_matrix: Record<string, Record<string, number>>;
  correlation_symbols: string[];
  regime_map: RegimeMapEntry[];
  factor_rotation: FactorRotationEntry[];
  as_of?: string;
}

function corrColor(value: number): string {
  if (value >= 0.7) return "bg-terminal-up/40 text-terminal-up";
  if (value >= 0.3) return "bg-terminal-up/15 text-qa-text";
  if (value <= -0.7) return "bg-terminal-down/40 text-terminal-down";
  if (value <= -0.3) return "bg-terminal-down/15 text-qa-text";
  return "bg-cockpit-panel-raised text-qa-muted";
}

export function GlobalMacroPanel({ macro }: { macro: GlobalMacroData | null | undefined }) {
  if (!macro) return null;

  const symbols = macro.correlation_symbols;

  return (
    <section className="cockpit-panel p-4 space-y-5">
      <div className="flex items-center gap-2 text-terminal-accent">
        <Globe size={16} />
        <h2 className="text-sm font-bold uppercase tracking-wide">Мировой и макрофон</h2>
      </div>

      {macro.regime_map.length > 0 && (
        <div>
          <h3 className="text-xs uppercase text-qa-muted mb-2">Режимы рынков</h3>
          <div className="flex flex-wrap gap-2">
            {macro.regime_map.map((entry) => (
              <div
                key={entry.symbol}
                className="rounded-lg border border-cockpit-border bg-cockpit-panel-raised px-3 py-2 min-w-[140px]"
              >
                <p className="text-sm font-mono font-semibold text-white">{entry.symbol}</p>
                <p className="text-xs text-terminal-accent">{entry.dominant_regime_ru}</p>
                <p className="text-[10px] text-qa-muted">
                  conf {(entry.confidence * 100).toFixed(0)}%
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {symbols.length >= 2 && (
        <div className="overflow-x-auto">
          <h3 className="text-xs uppercase text-qa-muted mb-2">Корреляции</h3>
          <table className="text-xs font-mono">
            <thead>
              <tr>
                <th className="p-1" />
                {symbols.map((s) => (
                  <th key={s} className="p-1 text-qa-muted font-normal">
                    {s.length > 6 ? s.slice(0, 5) + "…" : s}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {symbols.map((rowSym) => (
                <tr key={rowSym}>
                  <td className="p-1 text-qa-muted">{rowSym.length > 6 ? rowSym.slice(0, 5) + "…" : rowSym}</td>
                  {symbols.map((colSym) => {
                    const val = macro.correlation_matrix[rowSym]?.[colSym] ?? 0;
                    return (
                      <td key={colSym} className="p-0.5">
                        <div
                          className={clsx(
                            "w-10 h-7 flex items-center justify-center rounded tabular-nums",
                            corrColor(val),
                          )}
                        >
                          {val.toFixed(2)}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {macro.factor_rotation.length > 0 && (
        <div>
          <div className="flex items-center gap-2 text-terminal-up mb-2">
            <Layers size={14} />
            <h3 className="text-xs uppercase">Ротация факторов</h3>
          </div>
          <div className="space-y-1">
            {macro.factor_rotation.map((f) => (
              <div
                key={f.factor}
                className="flex items-center justify-between rounded-lg px-3 py-1.5 bg-cockpit-panel-raised border border-cockpit-border text-sm"
              >
                <span className="text-qa-text">
                  <span className="text-qa-muted mr-2">#{f.rank}</span>
                  {f.factor}
                </span>
                <span
                  className={clsx(
                    "font-mono tabular-nums text-xs",
                    f.direction === "outperform"
                      ? "text-terminal-up"
                      : f.direction === "underperform"
                        ? "text-terminal-down"
                        : "text-qa-muted",
                  )}
                >
                  {f.score >= 0 ? "+" : ""}
                  {f.score.toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
