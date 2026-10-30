"use client";

import { useMemo } from "react";
import { format, parseISO } from "date-fns";
import { ru } from "date-fns/locale";
import { clsx } from "clsx";
import { AlertTriangle, Layers } from "lucide-react";
import { FORECAST_TIMEOUT_MESSAGE_RU } from "@/lib/api";
import { extractErrorMessage } from "@/lib/errors";
import { pct } from "@/lib/forecast-hierarchy";
import { useTickerForecast } from "@/hooks/useTickerForecast";
import type { ForecastHierarchyView } from "@/types/forecast-hierarchy";
import { ScenarioDisclosureBlock } from "@/components/forecasting/ScenarioDisclosureBlock";
import { ShapFactorsChart } from "@/components/forecasting/ShapFactorsChart";
import { MarketBeatPanel } from "@/components/forecasting/MarketBeatPanel";
import { TrackRecordPanel } from "@/components/forecasting/TrackRecordPanel";
import { ForecastEnsemblePanel } from "@/components/forecasting/ForecastEnsemblePanel";
import { BullBaseBearPanel } from "@/components/forecasting/BullBaseBearPanel";
import { GlobalMacroPanel } from "@/components/forecasting/GlobalMacroPanel";
import { Spinner } from "@/components/ui";

function formatAsOf(asOf: string | null | undefined, fallbackMs?: number): string {
  if (asOf) {
    try {
      return format(parseISO(asOf), "dd MMM yyyy, HH:mm", { locale: ru });
    } catch {
      return asOf;
    }
  }
  if (fallbackMs) {
    return format(new Date(fallbackMs), "dd MMM yyyy, HH:mm", { locale: ru });
  }
  return "—";
}

const FACTOR_RU: Record<string, string> = {
  value: "Стоимость (value)",
  growth: "Рост (growth)",
  momentum: "Импульс",
  market_beta: "Рынок в целом (бета)",
  fx_sensitivity: "Курс валют",
  sector_factor: "Сектор",
  commodity_sensitivity: "Сырьё",
  volatility_factor: "Волатильность",
  size: "Размер компании",
  quality: "Качество",
  rate_sensitivity: "Процентные ставки",
};

function signedPct(x: number | null | undefined): string {
  if (x == null || !Number.isFinite(x)) return "—";
  const v = x * 100;
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

/** Range and risk in plain words: the numbers an investor needs, without engine names. */
function RangeAndRiskPanel({ view }: { view: ForecastHierarchyView }) {
  const iv = view.interval_forecast;
  const m = (view.risk_forecast?.metrics ?? {}) as Record<string, number | undefined>;
  const rows: Array<[string, string, string]> = [];
  if (iv && (iv.p10 || iv.p90)) {
    rows.push([
      `Диапазон цены, ${iv.horizon_ru ?? "10 дней"}`,
      `${signedPct(iv.p10)} … ${signedPct(iv.p90)}`,
      "С вероятностью 80% изменение цены уложится в этот коридор.",
    ]);
  }
  if (m.composite_risk_score != null) {
    rows.push(["Общий риск бумаги", pct(m.composite_risk_score), "Сводная оценка: волатильность, хвосты, ликвидность, события."]);
  }
  if (m.tail_risk_score != null) {
    rows.push(["Риск резкого падения", pct(m.tail_risk_score), "Насколько часто в истории бумаги случались провалы сильнее обычного."]);
  }
  if (m.volatility_expansion_probability != null) {
    rows.push(["Вероятность роста волатильности", pct(m.volatility_expansion_probability), "Шанс, что колебания цены заметно усилятся."]);
  }
  if (m.liquidity_risk_score != null) {
    rows.push(["Риск ликвидности", pct(m.liquidity_risk_score), "Сложность продать позицию без заметного влияния на цену."]);
  }
  if (!rows.length) return null;
  return (
    <section className="cockpit-panel p-4">
      <h2 className="text-sm font-bold uppercase tracking-wide text-terminal-accent mb-3">Диапазон и риск</h2>
      <ul className="divide-y divide-cockpit-border/60">
        {rows.map(([label, value, hint]) => (
          <li key={label} className="py-2.5 flex items-start justify-between gap-4">
            <div>
              <p className="text-sm text-qa-text">{label}</p>
              <p className="text-[11px] text-qa-muted">{hint}</p>
            </div>
            <span className="font-mono tabular-nums text-white font-semibold whitespace-nowrap">{value}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11px] text-qa-muted">Вероятностная оценка, не гарантия результата.</p>
    </section>
  );
}

/** Full Forecast engine desk — same layers as /forecasting. Never condense. */
const AI_LABELS: Record<string, string> = {
  вердикт: "Вывод",
  почему: "Почему",
  "что изменит взгляд": "Что изменит оценку",
  действие: "Что учесть",
};

/** Split the AI text into paragraphs; "Вердикт - …" style prefixes become readable labels. */
function aiParagraphs(text: string): { label: string | null; text: string }[] {
  return text
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const m = line.match(/^(Вердикт|Почему|Что изменит взгляд|Действие)\s*[-–—:]\s*(.*)$/i);
      if (!m) return { label: null, text: line };
      return { label: AI_LABELS[m[1].toLowerCase()] ?? m[1], text: m[2] };
    });
}

export function TickerForecastDesk({
  symbol,
  className,
}: {
  symbol: string;
  className?: string;
}) {
  const {
    data,
    hierarchyView,
    isLoading,
    isFetching,
    error,
    dataUpdatedAt,
    narrativeLoading,
    narrativeError,
    narrativeMessage,
    refetchNarrative,
    refetchAll,
    aiRequested,
    requestAiExplanation,
  } = useTickerForecast(symbol);

  const scenarioDisclosure = data?.scenario_disclosure ?? null;
  // Spinner only while the request is in flight; an answer without scenarios is an empty state.
  const disclosureLoading = narrativeLoading && !scenarioDisclosure?.paragraphs?.length;

  const factorRows = useMemo(() => {
    if (!data?.factor_exposures) return [];
    return Object.entries(data.factor_exposures)
      .filter(([, weight]) => weight != null && Number.isFinite(weight))
      .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
      .slice(0, 8);
  }, [data]);

  return (
    <div className={clsx("space-y-6", className)}>
      {!error ? (
        <ScenarioDisclosureBlock
          disclosure={scenarioDisclosure}
          isLoading={disclosureLoading}
          symbol={symbol}
        />
      ) : null}

      {data && !aiRequested ? (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-cockpit-border px-3 py-2">
          <p className="text-xs text-qa-muted">
            Текст выше собран по расчётам платформы. Развёрнутое пояснение пишет ИИ — по запросу.
          </p>
          <button type="button" onClick={requestAiExplanation} className="btn-primary text-xs shrink-0">
            Пояснение ИИ
          </button>
        </div>
      ) : null}

      {aiRequested && narrativeLoading && data ? (
        <div className="cockpit-panel p-4 flex items-center gap-3" aria-live="polite">
          <Spinner size={16} />
          <p className="text-sm text-qa-muted">ИИ готовит пояснение по {symbol} — обычно 10–40 секунд.</p>
        </div>
      ) : null}

      {aiRequested && !narrativeLoading && data?.llm_narrative ? (
        // The AI text also updates the scenario block at the top of the page; it is shown here
        // too, right where the button was, so the result is visible after the click.
        <section className="cockpit-panel p-4 space-y-2" aria-live="polite">
          <h3 className="text-sm font-bold uppercase tracking-wide text-terminal-accent">Пояснение ИИ</h3>
          {aiParagraphs(data.llm_narrative).map((p, i) => (
            <p key={i} className="text-sm text-qa-text/90 leading-relaxed">
              {p.label ? <span className="font-semibold text-qa-text">{p.label}. </span> : null}
              {p.text}
            </p>
          ))}
          <p className="text-[11px] text-qa-muted">
            Текст написан ИИ по расчётам платформы. Это не индивидуальная инвестиционная рекомендация.
          </p>
        </section>
      ) : null}

      {narrativeError && !narrativeLoading && data && (
        <div className="cockpit-panel p-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <p className="text-sm text-qa-muted">
            {extractErrorMessage(narrativeError, narrativeMessage)}
          </p>
          <button
            type="button"
            onClick={() => void refetchNarrative()}
            className="btn-primary text-xs shrink-0"
          >
            Повторить пояснение ИИ
          </button>
        </div>
      )}

      {!isLoading && !error && data?.market_beat && (
        <MarketBeatPanel beat={data.market_beat} />
      )}

      {!isLoading && !error && data?.track_record_chart && (
        <TrackRecordPanel chart={data.track_record_chart} />
      )}

      {!isLoading && !error && (data?.ensemble_forecast || data?.conformal_intervals) && (
        <ForecastEnsemblePanel
          ensemble={data?.ensemble_forecast}
          intervals={data?.conformal_intervals}
          liveDirectionAccuracy={data?.live_direction_accuracy}
        />
      )}

      {!isLoading && !error && data?.bull_base_bear && data.bull_base_bear.length > 0 && (
        <BullBaseBearPanel scenarios={data.bull_base_bear} />
      )}

      {!isLoading && !error && data?.global_macro && (
        <GlobalMacroPanel macro={data.global_macro} />
      )}

      {isLoading ? (
        <div className="flex flex-col items-center justify-center py-24 gap-3">
          <Spinner size={28} />
          <p className="text-sm text-qa-muted">Загрузка прогноза для {symbol}…</p>
        </div>
      ) : error ? (
        <div className="cockpit-panel p-6 text-center">
          <AlertTriangle size={24} className="mx-auto text-terminal-accent mb-2" />
          <p className="text-sm text-qa-text">
            {extractErrorMessage(error, FORECAST_TIMEOUT_MESSAGE_RU)}
          </p>
          <button type="button" onClick={refetchAll} className="mt-4 btn-primary text-xs">
            Повторить
          </button>
        </div>
      ) : data && hierarchyView ? (
        <>
          <div className="flex flex-wrap items-center gap-3 text-xs text-qa-muted">
            <span>Обновлено: {formatAsOf(hierarchyView.as_of, dataUpdatedAt)}</span>
            {isFetching && <span className="text-terminal-accent">обновление…</span>}
            <span className="text-qa-muted">·</span>
            <span>уверенность модели {pct(hierarchyView.calibrated_confidence)}</span>
          </div>

          <RangeAndRiskPanel view={hierarchyView} />

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {data.ticker_analysis?.shap_available && data.ticker_analysis.shap_top_factors?.length ? (
              <div className="cockpit-panel p-4">
                <div className="flex items-center gap-2 text-terminal-accent mb-3">
                  <Layers size={16} />
                  <h2 className="text-sm font-bold uppercase tracking-wide">Что сильнее всего влияет на оценку</h2>
                </div>
                <ShapFactorsChart analysis={data.ticker_analysis} />
              </div>
            ) : null}

            {factorRows.length > 0 ? (
              <div className="cockpit-panel p-4">
                <div className="flex items-center gap-2 text-terminal-up mb-3">
                  <Layers size={16} />
                  <h2 className="text-sm font-bold uppercase tracking-wide">Чувствительность к факторам</h2>
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-[11px] uppercase text-qa-muted border-b border-cockpit-border">
                      <th className="pb-2 pr-4">Фактор</th>
                      <th className="pb-2 text-right">Бета</th>
                    </tr>
                  </thead>
                  <tbody>
                    {factorRows.map(([factor, weight]) => (
                      <tr key={factor} className="border-b border-cockpit-border/60 last:border-0">
                        <td className="py-2.5 pr-4 text-qa-text">{FACTOR_RU[factor] ?? factor.replace(/_/g, " ")}</td>
                        <td className="py-2.5 text-right font-mono tabular-nums text-white">
                          {weight >= 0 ? "+" : ""}
                          {weight.toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-2 text-[11px] text-qa-muted">
                  Насколько цена бумаги реагирует на каждый фактор. Значения по модулю больше 1 — сильная связь.
                </p>
              </div>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  );
}
