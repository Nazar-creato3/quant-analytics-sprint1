"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useChartColors } from "@/hooks/useChartColors";
import type { ChartColorPalette } from "@/lib/chartColors";

interface CalibrationBin {
  predicted_confidence: number;
  observed_frequency: number;
  count: number;
}

interface RollingAccuracyPoint {
  window_days: number;
  regime_match_accuracy?: number;
  /** @deprecated use regime_match_accuracy */
  directional_accuracy?: number;
  mae: number;
  sample_size: number;
  ci_low?: number | null;
  ci_high?: number | null;
}

export interface TrackRecordChartData {
  calibration_bins: CalibrationBin[];
  rolling_accuracy: RollingAccuracyPoint[];
  aggregate_calibration_error?: number | null;
  /** @deprecated use aggregate_calibration_error */
  live_vs_backtest_gap?: number | null;
  drift_flag: boolean;
  data_source?: string;
  disclaimer_ru?: string;
}

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

/** «46.7% (95% ДИ: 38–56%, n=142)» */
export function formatAccuracyWithCiRu(
  accuracy: number | null | undefined,
  ciLow?: number | null,
  ciHigh?: number | null,
  sampleSize?: number | null,
): string {
  if (accuracy == null) return "—";
  const base = pct(accuracy);
  if (ciLow == null || ciHigh == null || sampleSize == null) return base;
  const lo = Math.round(ciLow * 100);
  const hi = Math.round(ciHigh * 100);
  return `${base} (95% ДИ: ${lo}–${hi}%, n=${sampleSize})`;
}

function regimeMatchAccuracy(pt: RollingAccuracyPoint): number {
  return pt.regime_match_accuracy ?? pt.directional_accuracy ?? 0;
}

function aggregateCalibrationError(chart: TrackRecordChartData): number | null | undefined {
  return chart.aggregate_calibration_error ?? chart.live_vs_backtest_gap;
}

function rechartsTooltipStyle(colors: ChartColorPalette) {
  return {
    background: colors.panel,
    border: `1px solid ${colors.crosshair}`,
    borderRadius: 8,
    fontSize: 12,
    color: colors.liveNeutral,
  };
}

export function CalibrationChart({ bins }: { bins: CalibrationBin[] }) {
  const colors = useChartColors();

  if (!bins.length) {
    return (
      <p className="text-sm text-qa-muted">
        Недостаточно данных для диаграммы калибровки.
      </p>
    );
  }

  const data = bins.map((b) => ({
    label: pct(b.predicted_confidence),
    predicted: b.predicted_confidence,
    observed: b.observed_frequency,
    count: b.count,
  }));

  return (
    <div className="h-48">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={colors.border} />
          <XAxis dataKey="label" tick={{ fill: colors.textMuted, fontSize: 10 }} />
          <YAxis
            domain={[0, 1]}
            tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
            tick={{ fill: colors.textMuted, fontSize: 10 }}
          />
          <Tooltip
            contentStyle={rechartsTooltipStyle(colors)}
            formatter={(value: number, name: string) => [
              pct(value),
              name === "predicted" ? "За заявленную уверенность" : "Фактическая частота",
            ]}
          />
          <Bar dataKey="predicted" name="predicted" fill={colors.accent} opacity={0.5} />
          <Bar dataKey="observed" name="observed" fill={colors.success} />
        </BarChart>
      </ResponsiveContainer>
      <p className="text-[10px] text-qa-muted mt-1">
        Оранжевый — заявленная уверенность; зелёный — фактическая частота попаданий режима.
      </p>
    </div>
  );
}

export function TrackRecordPanel({ chart }: { chart: TrackRecordChartData | null | undefined }) {
  if (!chart) {
    return (
      <div className="cockpit-panel p-4">
        <h2 className="text-sm font-bold uppercase tracking-wide text-terminal-accent mb-2">
          История точности
        </h2>
        <p className="text-sm text-qa-muted">Загрузка статистики точности…</p>
      </div>
    );
  }

  const calError = aggregateCalibrationError(chart);

  return (
    <section className="cockpit-panel p-4 space-y-4" id="track-record">
      <div>
        <h2 className="text-sm font-bold uppercase tracking-wide text-terminal-accent mb-1">
          Track Record — честная статистика
        </h2>
        <p className="text-xs text-qa-muted">
          Калибровка и точность классификации режима на тесте.
        </p>
        {chart.data_source === "synthetic_fallback" && (
          <p className="text-xs text-qa-warning/90 mt-1">
            Предварительная статистика на тестовых данных — не финальная.
          </p>
        )}
      </div>

      {chart.drift_flag && (
        <div className="rounded-lg alert-caution px-3 py-2 text-xs text-qa-text">
          Повышенная ошибка калибровки на эталонных рядах (
          {calError?.toFixed(3) ?? "—"}). Интерпретируйте прогнозы осторожнее.
        </div>
      )}

      <div>
        <h3 className="text-xs uppercase text-qa-muted mb-2">Диаграмма калибровки</h3>
        <CalibrationChart bins={chart.calibration_bins} />
      </div>

      {chart.rolling_accuracy.length > 0 && (
        <div>
          <h3 className="text-xs uppercase text-qa-muted mb-2">
            Точность классификации режима (тест)
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            {chart.rolling_accuracy.map((pt) => (
              <div
                key={pt.window_days}
                className="rounded-lg bg-cockpit-panel-raised border border-cockpit-border px-3 py-2"
                title={
                  pt.sample_size < 50
                    ? "Малая выборка — статистика менее надёжна"
                    : undefined
                }
              >
                <p className="text-[10px] text-qa-muted">{pt.window_days}d window</p>
                <p className="text-lg font-mono tabular-nums text-qa-text">
                  {formatAccuracyWithCiRu(
                    regimeMatchAccuracy(pt),
                    pt.ci_low,
                    pt.ci_high,
                    pt.sample_size,
                  )}
                </p>
                <p className="text-[10px] text-qa-muted">
                  Ошибка калибровки {pt.mae.toFixed(3)}
                  {pt.ci_low == null ? ` · n=${pt.sample_size}` : ""}
                </p>
                {pt.sample_size < 50 && (
                  <p className="text-[10px] text-qa-warning/90 mt-1">
                    Малая выборка (n={pt.sample_size}) — интерпретируйте осторожнее.
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
