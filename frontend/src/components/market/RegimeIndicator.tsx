"use client";

import { useQuery } from "@tanstack/react-query";
import { forecastApi } from "@/lib/api";
import { queryKeys } from "@/lib/queryKeys";

const REGIME_RU: Record<string, string> = {
  trend_up: "восходящий тренд",
  trend_down: "нисходящий тренд",
  range: "боковое движение",
  choppy_range: "боковое движение",
  sideways: "боковое движение",
  high_volatility: "высокая волатильность",
  high_volatility_shock: "резкий всплеск волатильности",
  calm: "спокойный рынок",
  insufficient: "мало данных",
  insufficient_data: "мало данных",
  insufficient_history: "мало данных",
};

export function regimeLabelRu(label: string | null | undefined): string {
  if (!label) return "нет данных";
  return REGIME_RU[label] ?? label.replace(/_/g, " ");
}

export function RegimeIndicator({ ticker, compact = false }: { ticker?: string; compact?: boolean }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.regime(ticker),
    queryFn: () => forecastApi.regime(ticker),
  });
  if (isLoading) {
    return <p className="text-xs text-qa-muted">Режим рынка: загрузка…</p>;
  }
  if (
    isError ||
    !data?.market ||
    data.market.status === "insufficient_data" ||
    data.market.label === "insufficient" ||
    !data.market.label
  ) {
    return <p className="text-xs text-qa-muted">Режим рынка: нет данных</p>;
  }
  if (compact) {
    return (
      <span className="text-[10px] uppercase tracking-wide text-qa-muted">
        Режим: {regimeLabelRu(data.market.label)}
        {data.instrument ? ` / ${data.instrument.ticker}: ${regimeLabelRu(data.instrument.label)}` : ""}
      </span>
    );
  }
  return (
    <div className="cockpit-panel p-4">
      <p className="text-[10px] uppercase tracking-wide text-qa-muted">Режим рынка</p>
      <p className="text-sm mt-1">
        Рынок ({data.market.ticker}): {regimeLabelRu(data.market.label)}
        {data.instrument ? ` · ${data.instrument.ticker}: ${regimeLabelRu(data.instrument.label)}` : ""}
      </p>
      <p className="text-xs text-qa-muted mt-1">{data.market.explain}</p>
    </div>
  );
}
