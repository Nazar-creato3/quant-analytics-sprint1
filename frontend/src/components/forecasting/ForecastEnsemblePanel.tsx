"use client";

import { clsx } from "clsx";
import { Layers, TrendingDown, TrendingUp, Minus } from "lucide-react";

interface EnsembleModel {
  family: string;
  family_label?: string;
  family_label_ru?: string;
  direction: number;
  expected_return: number;
  weight: number;
  recent_accuracy: number;
  available: boolean;
  note?: string;
}

export interface EnsembleForecastData {
  median_return: number;
  direction_consensus: number;
  models_agreeing: number;
  models_total: number;
  insufficient_history: boolean;
  history_bars: number;
  component_models: EnsembleModel[];
}

export interface ConformalIntervalData {
  horizon_days: number;
  median_return: number;
  lower_70: number;
  upper_70: number;
  lower_90: number;
  upper_90: number;
  method: string;
  sufficient_data: boolean;
}

const FAMILY_LABELS_RU: Record<string, string> = {
  arima: "ARIMA",
  momentum: "Моментум",
  confidence_heuristic: "Эвристика по порогу уверенности",
  lightgbm_signal: "Эвристика по порогу уверенности",
};

function modelLabelRu(m: EnsembleModel): string {
  return m.family_label_ru ?? FAMILY_LABELS_RU[m.family] ?? m.family.replace(/_/g, " ");
}

function pct(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(2)}%`;
}

function DirectionIcon({ direction }: { direction: number }) {
  if (direction > 0) return <TrendingUp size={14} className="text-terminal-up" />;
  if (direction < 0) return <TrendingDown size={14} className="text-terminal-down" />;
  return <Minus size={14} className="text-qa-muted" />;
}

export function ForecastEnsemblePanel({
  ensemble,
  intervals,
  liveDirectionAccuracy,
}: {
  ensemble: EnsembleForecastData | null | undefined;
  intervals: ConformalIntervalData | null | undefined;
  liveDirectionAccuracy?: import("@/types").LiveDirectionAccuracy | null;
}) {
  if (!ensemble && !intervals) return null;

  const liveMembers = (ensemble?.component_models ?? []).filter((m) => m.available);

  if (ensemble?.insufficient_history) {
    return (
      <section className="cockpit-panel p-4">
        <div className="flex items-center gap-2 text-terminal-accent mb-2">
          <Layers size={16} />
          <h2 className="text-sm font-bold uppercase tracking-wide">Сводный прогноз</h2>
        </div>
        <p className="text-sm text-qa-muted">
          Недостаточно истории ({ensemble.history_bars} баров) для надёжного ensemble-прогноза.
          Минимум 30 дневных баров.
        </p>
      </section>
    );
  }

  return (
    <section className="cockpit-panel p-4 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-terminal-accent">
          <Layers size={16} />
          <h2 className="text-sm font-bold uppercase tracking-wide">Сводный прогноз</h2>
        </div>
        <span className="text-xs text-qa-muted font-mono">
          {ensemble
            ? `Консенсус: ${ensemble.models_agreeing}/${ensemble.models_total} живых`
            : "Только интервал — ансамбль недоступен"}
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="rounded-lg bg-cockpit-panel-raised border border-cockpit-border p-3">
          <p className="text-[10px] uppercase text-qa-muted mb-1">30-day median path</p>
          <p className="text-2xl font-mono tabular-nums text-white flex items-center gap-2">
            <DirectionIcon direction={ensemble?.direction_consensus ?? 0} />
            {ensemble ? pct(ensemble.median_return) : "—"}
          </p>
        </div>

        {intervals && !intervals.sufficient_data && (
          <p className="text-xs text-qa-muted md:col-span-1">
            Conformal не готов — это «не знаем», не узкий интервал из воздуха.
          </p>
        )}
        {intervals && intervals.sufficient_data && (
          <div className="rounded-lg bg-cockpit-panel-raised border border-cockpit-border p-3 space-y-2">
            <p className="text-[10px] uppercase text-qa-muted">
              Conformal intervals ({intervals.method})
            </p>
            <div className="space-y-1 text-sm font-mono">
              <div className="flex justify-between text-qa-text">
                <span className="text-qa-muted">70% band</span>
                <span>
                  {pct(intervals.lower_70)} … {pct(intervals.upper_70)}
                </span>
              </div>
              <div className="relative h-3 rounded bg-cockpit-bg overflow-hidden">
                <div
                  className="absolute h-full bg-terminal-accent/20"
                  style={{
                    left: "15%",
                    right: "15%",
                  }}
                />
                <div
                  className="absolute h-full bg-terminal-accent/40"
                  style={{
                    left: "25%",
                    right: "25%",
                  }}
                />
              </div>
              <div className="flex justify-between text-qa-text">
                <span className="text-qa-muted">90% band</span>
                <span>
                  {pct(intervals.lower_90)} … {pct(intervals.upper_90)}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>

      <div>
        <p className="text-[10px] uppercase text-qa-muted mb-2">
          Компоненты (только доступные сейчас)
        </p>
        <div className="space-y-1.5">
          {liveMembers.map((m) => (
            <div
              key={m.family}
              className={clsx(
                "flex items-center justify-between rounded-lg px-3 py-2",
                "bg-cockpit-panel-raised border border-cockpit-border text-sm",
              )}
            >
              <div className="flex items-center gap-2">
                <DirectionIcon direction={m.direction} />
                <span className="text-qa-text">{modelLabelRu(m)}</span>
                {m.note && (
                  <span className="text-[10px] text-qa-muted truncate max-w-[120px]">{m.note}</span>
                )}
              </div>
              <div className="flex items-center gap-3 font-mono tabular-nums text-xs">
                <span className="text-white">{pct(m.expected_return)}</span>
                <span className="text-terminal-accent">w={(m.weight * 100).toFixed(0)}%</span>
                <span className="text-qa-muted">acc={(m.recent_accuracy * 100).toFixed(0)}%</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {liveDirectionAccuracy && liveDirectionAccuracy.sample_size > 0 && (
        <p className="text-xs text-qa-muted border-t border-cockpit-border pt-3">
          Live direction accuracy ({liveDirectionAccuracy.window_days ?? 30}d):{" "}
          <span className="text-white font-mono">
            {liveDirectionAccuracy.formatted_ru ??
              (liveDirectionAccuracy.accuracy != null
                ? `${(liveDirectionAccuracy.accuracy * 100).toFixed(1)}% (n=${liveDirectionAccuracy.sample_size})`
                : "—")}
          </span>
        </p>
      )}
    </section>
  );
}
