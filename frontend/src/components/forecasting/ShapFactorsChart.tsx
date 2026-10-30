"use client";

import { useMemo } from "react";
import {
  Bar,
  BarChart,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TickerAnalysisPayload } from "@/types";
import { useChartColors } from "@/hooks/useChartColors";
import type { ChartColorPalette } from "@/lib/chartColors";

type ShapRow = {
  label: string;
  contribution: number;
  fill: string;
};

const FEATURE_LABELS: Record<string, string> = {
  momentum_12m: "ход за год",
  value: "насколько бумага дешёвая относительно прибыли",
  volatility: "волатильность цены",
  rsi_14: "перекупленность или перепроданность",
  volume_ratio: "объём относительно обычного",
};

function featureLabel(feature: string): string {
  const key = feature.toLowerCase();
  return FEATURE_LABELS[key] ?? feature.replace(/_/g, " ");
}

function rechartsTooltipStyle(colors: ChartColorPalette) {
  return {
    background: colors.panel,
    border: `1px solid ${colors.border}`,
    fontSize: 12,
    color: colors.liveNeutral,
  };
}

export function ShapFactorsChart({
  analysis,
}: {
  analysis: TickerAnalysisPayload | null | undefined;
}) {
  const colors = useChartColors();

  const rows = useMemo((): ShapRow[] => {
    if (!analysis?.shap_available || !analysis.shap_top_factors?.length) {
      return [];
    }
    return analysis.shap_top_factors.slice(0, 8).map((f) => ({
      label: featureLabel(f.feature),
      contribution: f.contribution,
      fill: f.contribution >= 0 ? colors.positiveBar : colors.negativeBar,
    }));
  }, [analysis, colors]);

  if (!analysis?.shap_available) {
    return (
      <div className="text-sm text-qa-muted space-y-1">
        <p>Пока не из чего показать, что сильнее всего тянет оценку этой бумаги.</p>
        <p className="text-[11px] text-qa-muted">
          Нужна обученная модель и полный набор признаков.
        </p>
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <p className="text-sm text-qa-muted">
        Модель загружена, но вклад отдельных факторов ещё не посчитан.
      </p>
    );
  }

  return (
    <div className="w-full min-w-0 overflow-x-auto">
      <ResponsiveContainer width="100%" height={Math.max(160, rows.length * 36)}>
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 12, left: 4, bottom: 4 }}>
          <XAxis type="number" tick={{ fill: colors.textMuted, fontSize: 10 }} domain={["auto", "auto"]} />
          <YAxis
            type="category"
            dataKey="label"
            width={100}
            tick={{ fill: colors.liveNeutral, fontSize: 11 }}
          />
          <Tooltip
            formatter={(v: number) => [v.toFixed(3), "вклад"]}
            contentStyle={rechartsTooltipStyle(colors)}
          />
          <ReferenceLine x={0} stroke={colors.crosshair} />
          <Bar dataKey="contribution" radius={[0, 4, 4, 0]}>
            {rows.map((row) => (
              <Cell key={row.label} fill={row.fill} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="text-[10px] text-qa-muted mt-2">
        Плюс тянет оценку вверх, минус — вниз. Это объяснение модели, не гарантия.
      </p>
    </div>
  );
}
