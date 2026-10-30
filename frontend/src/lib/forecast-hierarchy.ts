import { labelMetric, labelModel, labelSource } from "@/lib/user-facing-labels";

export { labelMetric, labelModel, labelSource };

import type { ForecastData, MarketForecastData } from "@/types";
import type {
  ActionForecast,
  ActionRecommendation,
  DistributionForecast,
  ForecastHierarchyOutput,
  ForecastHierarchyView,
  ForecastInstructionBlock,
  ForecastPredictionItem,
  IntervalForecast,
  LayerBasis,
  MarketOutlookCard,
  MarketOutlookEntry,
  MarketOutlookPoint,
  MarketOutlookScenario,
  PointForecast,
  PointMagnitude,
  RegimeContext,
  RegimeForecastSection,
  RiskForecast,
  ScenarioArchetype,
  ScenarioForecast,
  ScenarioForecastItem,
  StructuredForecastSections,
} from "@/types/forecast-hierarchy";

export const FORECAST_DISCLAIMER =
  "Вероятностная оценка, не гарантия результата";

export const LAYER_TOOLTIPS_RU: Record<string, string> = {
  point:
    "Point Forecast — ожидаемое направление и сила движения цены на коротком горизонте.",
  interval:
    "Interval — диапазон возможной доходности (P10–P90): где с высокой вероятностью окажется цена.",
  distribution:
    "Distribution — полное распределение доходности по перцентилям (P5–P95), не только медиана.",
  scenario:
    "Scenario — четыре взаимоисключающих исхода (сумма ≈100%): пессимистичный, реалистичный, оптимистичный, классический. Impact — ожидаемая доходность в каждом сценарии.",
  risk:
    "Risk — метрики Risk Engine: композитный риск, флаги и пороговые нарушения по инструменту.",
  action:
    "Action — правило-based рекомендация по размеру позиции с учётом риска и уверенности.",
};

const SCENARIO_ARCHETYPE_RU: Record<ScenarioArchetype, string> = {
  pessimistic: "Пессимистичный",
  realistic: "Реалистичный",
  optimistic: "Оптимистичный",
  classic: "Классический",
};

export const HIGH_CONFIDENCE_THRESHOLD = 0.85;
export const CLOSE_SCENARIO_THRESHOLD = 0.05;

export const ACTION_LABELS_RU: Record<ActionRecommendation, string> = {
  wait: "Выжидание",
  reduce_size: "Уменьшить размер",
  hedge: "Хеджирование",
  hold: "Удержание",
  enter_small_size: "Вход малым размером",
  enter_normal_size: "Вход нормальным размером",
  avoid: "Избегать",
};

export const MAGNITUDE_LABELS_RU: Record<PointMagnitude, string> = {
  strong_up: "Сильный рост",
  up: "Рост",
  neutral: "Неопределённо",
  down: "Снижение",
  strong_down: "Сильное снижение",
};

export const ENGINE_LABELS_RU: Record<string, string> = {
  RegimeEngine: "Regime Engine",
  GlobalRegimeEngine: "Global Regime Engine",
  SectorRegimeEngine: "Sector Regime Engine",
  ForecastEngine: "Forecast Engine",
  RiskEngine: "Risk Engine",
  ScenarioEngine: "Scenario Engine",
  ActionForecastEngine: "Action Forecast Engine",
  PredictionNarrator: "Prediction Narrator",
  ForecastConfidenceCalibrator: "Confidence Calibrator",
  FactorEngine: "Factor Engine",
  PredictionHierarchyOrchestrator: "Hierarchy Orchestrator",
};

const REGIME_RU: Record<string, string> = {
  bullish_trend: "бычий тренд",
  bearish_trend: "медвежий тренд",
  choppy_range: "боковик",
  high_volatility_shock: "шок волатильности",
  liquidity_drought: "дефицит ликвидности",
  macro_uncertainty: "макро-неопределённость",
  risk_on: "risk-on",
  risk_off: "risk-off",
  credit_stress: "кредитный стресс",
  inflation_shock_regime: "инфляционный шок",
};

export function pct(value: number | null | undefined): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${Math.round(Math.min(100, Math.max(0, n * 100)))}%`;
}

const DEFAULT_OUTLOOK_TITLES = ["Макро-режим", "Риск и волатильность", "Секторная ротация"];

export function isMarketOutlookPoint(entry: unknown): entry is MarketOutlookPoint {
  return (
    typeof entry === "object" &&
    entry !== null &&
    ("title" in entry || "what_happens" in entry || "prognosis" in entry)
  );
}

/** Coerce legacy string or enhanced object outlook entries to display text. */
export function outlookEntrySummary(entry: MarketOutlookEntry | unknown): string {
  if (typeof entry === "string") return entry;
  if (!isMarketOutlookPoint(entry)) return "—";
  return (
    entry.what_happens?.trim() ||
    entry.prognosis?.trim() ||
    entry.expectations?.trim() ||
    entry.title?.trim() ||
    "—"
  );
}

export function outlookEntryTitle(
  entry: MarketOutlookEntry | unknown,
  index: number,
  defaults: string[] = DEFAULT_OUTLOOK_TITLES,
): string {
  if (isMarketOutlookPoint(entry) && entry.title?.trim()) return entry.title.trim();
  return defaults[index] ?? `Outlook ${index + 1}`;
}

function safeNumber(value: unknown, fallback = 0): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function metricDisplay(
  value: unknown,
  dataQuality: Record<string, string> | undefined,
  key: string,
  metricValidity?: Record<string, boolean>,
): string {
  if (metricValidity?.[key] === false) return "н/д";
  if (dataQuality?.[key] === "insufficient_data") return "н/д";
  const n = safeNumber(value, NaN);
  if (!Number.isFinite(n)) return "н/д";
  if (n === 0 && dataQuality?.[key]) return "н/д";
  return pct(n);
}

function parseDataQuality(map: Record<string, unknown> | undefined): Record<string, string> {
  if (!map?._data_quality) return {};
  try {
    const raw = map._data_quality;
    if (typeof raw === "string") return JSON.parse(raw.replace(/'/g, '"')) as Record<string, string>;
    if (typeof raw === "object") return raw as Record<string, string>;
  } catch {
    return {};
  }
  return {};
}

function safeArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function momentumFromData(data: ForecastData): number {
  const map = data.probability_map ?? {};
  const raw = map.short_term_momentum ?? map.momentum_score;
  return safeNumber(raw, 0.5);
}

function compositeRiskFromData(data: ForecastData): number {
  return safeNumber(data.composite_risk_score, 0);
}

function volExpansionFromData(data: ForecastData, hierarchy: ForecastHierarchyOutput | null): number {
  const fromMap = data.probability_map?.volatility_expansion_probability;
  if (fromMap != null && Number.isFinite(Number(fromMap))) {
    return safeNumber(fromMap, 0);
  }
  const fromHierarchy = hierarchy?.risk_forecast?.metrics?.volatility_expansion_probability;
  if (fromHierarchy != null && Number.isFinite(Number(fromHierarchy))) {
    return safeNumber(fromHierarchy, 0);
  }
  const fromEngine = data.risk_engine_metrics?.volatility_expansion_probability;
  if (fromEngine != null && Number.isFinite(Number(fromEngine))) {
    return safeNumber(fromEngine, 0);
  }
  return 0;
}

export function engineLabel(engine: string): string {
  return ENGINE_LABELS_RU[engine] ?? engine;
}

export function regimeLabelRu(regime: string, labelRu?: string): string {
  return labelRu ?? REGIME_RU[regime] ?? regime.replace(/_/g, " ");
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

function asRegimeSection(
  value: RegimeForecastSection | Record<string, unknown> | undefined,
): RegimeForecastSection | null {
  if (!value || typeof value !== "object") return null;
  if ("dominant_regime" in value || "distribution" in value) {
    return value as RegimeForecastSection;
  }
  return null;
}

function extractHierarchy(data: ForecastData): ForecastHierarchyOutput | null {
  const raw =
    data.hierarchy ??
    data.forecast_output ??
    (data.hierarchy_output as ForecastHierarchyOutput | undefined);
  if (!raw || typeof raw !== "object") return null;
  return normalizeRawHierarchy(raw as Record<string, unknown>);
}

function normalizeRawHierarchy(raw: Record<string, unknown>): ForecastHierarchyOutput | null {
  if (raw.point_forecast && typeof raw.point_forecast === "object") {
    const pointRaw = raw.point_forecast as Record<string, unknown>;
    if ("momentum_score" in pointRaw && !("direction" in pointRaw)) {
      return mapBackendHierarchyOutput(raw);
    }
  }
  return raw as ForecastHierarchyOutput;
}

function mapBackendHierarchyOutput(raw: Record<string, unknown>): ForecastHierarchyOutput {
  const pointRaw = (raw.point_forecast ?? {}) as Record<string, unknown>;
  const intervalRaw = (raw.interval_forecast ?? {}) as Record<string, unknown>;
  const distRaw = (raw.distribution_forecast ?? {}) as Record<string, unknown>;
  const scenarioRaw = (raw.scenario_forecast ?? {}) as Record<string, unknown>;
  const riskRaw = (raw.risk_forecast ?? {}) as Record<string, unknown>;
  const actionRaw = (raw.action_forecast ?? {}) as Record<string, unknown>;
  const globalRaw = raw.global_regime as Record<string, unknown> | null | undefined;
  const sectorRaw = raw.sector_regime as Record<string, unknown> | null | undefined;

  const magnitude = String(pointRaw.magnitude_class ?? "neutral") as PointMagnitude;
  const sign = Number(pointRaw.expected_return_sign ?? 0);
  const direction: PointForecast["direction"] =
    sign > 0 ? "up" : sign < 0 ? "down" : "neutral";

  const horizonDays = Number(intervalRaw.horizon_days ?? 5);

  const instrumentMetrics = (riskRaw.instrument_metrics ?? {}) as Record<string, number>;
  const breached = (riskRaw.breached_metrics ?? []) as string[];

  const scenarios = Array.isArray(scenarioRaw.scenarios)
    ? (scenarioRaw.scenarios as Record<string, unknown>[]).map((s) => {
        const scenarioType = String(s.scenario_type ?? "");
        const name = String(s.name ?? "scenario");
        const archetype = isScenarioArchetype(scenarioType)
          ? scenarioType
          : isScenarioArchetype(name)
            ? name
            : undefined;
        return {
          name,
          label_ru: String(s.label_ru ?? s.name ?? "Сценарий"),
          probability: Number(s.probability ?? 0),
          impact: s.impact != null ? Number(s.impact) : null,
          engine: "ScenarioEngine",
          archetype,
        };
      })
    : [];

  return {
    point_forecast: {
      direction,
      magnitude,
      magnitude_ru: MAGNITUDE_LABELS_RU[magnitude] ?? magnitude,
      confidence: Number(pointRaw.momentum_score ?? 0.5),
      engine: "ForecastEngine",
    },
    interval_forecast: {
      horizon: `${horizonDays}D`,
      horizon_ru: `${horizonDays} дней`,
      p10: Number(intervalRaw.p10 ?? 0),
      p90: Number(intervalRaw.p90 ?? 0),
      unit: "return",
      engine: "RiskEngine",
    },
    distribution_forecast: {
      p5: Number(distRaw.p5 ?? 0),
      p25: Number(distRaw.p25 ?? 0),
      p50: Number(distRaw.p50 ?? 0),
      p75: Number(distRaw.p75 ?? 0),
      p95: Number(distRaw.p95 ?? 0),
      unit: "return",
      engine: "ScenarioEngine",
    },
    scenario_forecast: {
      scenarios,
      dispersion: Number(scenarioRaw.scenario_dispersion ?? 0),
      engine: "ScenarioEngine",
    },
    risk_forecast: {
      metrics: instrumentMetrics,
      composite_risk_score: Number(
        instrumentMetrics.composite_risk_score ?? instrumentMetrics.composite_risk ?? 0,
      ),
      risk_flags: breached.map(String),
      engine: "RiskEngine",
    },
    action_forecast: {
      recommendation: String(actionRaw.recommendation ?? "hold") as ActionRecommendation,
      label_ru: ACTION_LABELS_RU[String(actionRaw.recommendation ?? "hold") as ActionRecommendation],
      reason: String(actionRaw.reason ?? ""),
      engine: "ActionForecastEngine",
    },
    global_regime: globalRaw
      ? {
          dominant_regime: String(globalRaw.dominant_regime ?? "unknown"),
          dominant_regime_ru: regimeLabelRu(String(globalRaw.dominant_regime ?? "unknown")),
          confidence: Number(globalRaw.confidence ?? 0.5),
          distribution: Object.entries(
            (globalRaw.distribution as Record<string, number>) ?? {},
          ).map(([label, probability]) => ({
            label,
            label_ru: regimeLabelRu(label),
            probability,
            engine: "GlobalRegimeEngine",
          })),
          engine: "GlobalRegimeEngine",
        }
      : null,
    sector_regime: sectorRaw
      ? {
          dominant_regime: String(
            (sectorRaw.regime as Record<string, unknown> | undefined)?.dominant_regime ??
              sectorRaw.sector ??
              "sector",
          ),
          dominant_regime_ru: String(sectorRaw.sector ?? "Сектор"),
          confidence: Number(
            (sectorRaw.rotation as Record<string, unknown> | undefined)?.composite_score ?? 0.5,
          ),
          engine: "SectorRegimeEngine",
        }
      : null,
    calibrated_confidence: Number(raw.calibrated_confidence ?? 0.5),
    narrator_insights: Array.isArray(raw.narrator_insights)
      ? (raw.narrator_insights as { text_ru?: string }[]).map(
          (item) => item.text_ru ?? "",
        ).filter(Boolean)
      : [],
    as_of: typeof raw.as_of === "string" ? raw.as_of : null,
  };
}

function momentumToPoint(momentum: number): PointForecast {
  let magnitude: PointMagnitude = "neutral";
  let direction: PointForecast["direction"] = "neutral";

  if (momentum >= 0.65) {
    magnitude = "strong_up";
    direction = "up";
  } else if (momentum >= 0.55) {
    magnitude = "up";
    direction = "up";
  } else if (momentum <= 0.35) {
    magnitude = "strong_down";
    direction = "down";
  } else if (momentum <= 0.45) {
    magnitude = "down";
    direction = "down";
  }

  return {
    direction,
    magnitude,
    magnitude_ru: MAGNITUDE_LABELS_RU[magnitude],
    confidence: momentum,
    engine: "ForecastEngine",
  };
}

function buildInterval(data: ForecastData, volExpansion: number): IntervalForecast {
  const compositeRisk = compositeRiskFromData(data);
  const vol = clamp01(volExpansion * 0.35 + compositeRisk * 0.2 + 0.04);
  const mid = momentumFromData(data) - 0.5;
  return {
    horizon: "5D",
    horizon_ru: "5 дней",
    p10: mid - vol,
    p90: mid + vol,
    unit: "return",
    engine: "RiskEngine",
  };
}

function buildDistribution(interval: IntervalForecast, momentum: number): DistributionForecast {
  const spread = (interval.p90 - interval.p10) / 2;
  const mid = momentum - 0.5;
  return {
    p5: mid - spread * 1.2,
    p25: mid - spread * 0.55,
    p50: mid,
    p75: mid + spread * 0.55,
    p95: mid + spread * 1.2,
    unit: "return",
    engine: "ScenarioEngine",
  };
}

function buildScenarios(structured: StructuredForecastSections | null | undefined): ScenarioForecast {
  const outlook = safeArray<MarketOutlookScenario>(structured?.market_outlook);
  const tail = safeArray<ForecastPredictionItem>(structured?.tail_risk_events);
  const scenarios: ScenarioForecastItem[] = [
    ...outlook.map((item) => ({
      name: String(item?.scenario ?? "scenario"),
      label_ru: item?.label_ru ?? item?.scenario ?? "Сценарий",
      probability: safeNumber(item?.probability, 0),
      impact: null,
      engine: item?.engine ?? "ScenarioEngine",
    })),
    ...tail.slice(0, 4).map((item) => ({
      name: item?.label ?? "tail_risk",
      label_ru: item?.label_ru ?? item?.label ?? "Хвостовой риск",
      probability: safeNumber(item?.probability, 0),
      impact: safeNumber(item?.probability, 0),
      engine: item?.engine ?? "ScenarioEngine",
    })),
  ];

  const probs = scenarios.map((s) => s.probability);
  const dispersion =
    probs.length >= 2 ? Math.max(...probs) - Math.min(...probs) : 0;

  return {
    scenarios: scenarios.length
      ? scenarios
      : [
          {
            name: "baseline",
            label_ru: "Базовый сценарий",
            probability: 0.5,
            impact: 0,
            engine: "ForecastEngine",
          },
        ],
    dispersion,
    engine: "ScenarioEngine",
  };
}

function buildRisk(data: ForecastData, hierarchy: ForecastHierarchyOutput | null): RiskForecast {
  const metrics = { ...(data.risk_engine_metrics ?? {}) } as Record<
    string,
    number | string | boolean | null
  >;
  const composite = compositeRiskFromData(data);
  metrics.composite_risk_score = composite;
  metrics.confidence = safeNumber(data.confidence, 0);

  const hierarchyMetrics = hierarchy?.risk_forecast?.metrics;
  if (hierarchyMetrics && typeof hierarchyMetrics === "object") {
    for (const [key, value] of Object.entries(hierarchyMetrics)) {
      if (typeof value === "number" && Number.isFinite(value)) {
        metrics[key] = value;
      }
    }
  }

  const map = data.probability_map ?? {};
  for (const key of [
    "volatility_expansion_probability",
    "liquidity_deterioration_score",
    "tail_risk_score",
    "event_impact_score",
    "correlation_shift_score",
  ] as const) {
    const val = map[key];
    if (val != null && Number.isFinite(Number(val))) {
      metrics[key] = Number(val);
    }
  }

  const sourceRisk = data.source_metrics?.risk;
  if (sourceRisk && typeof sourceRisk === "object") {
    Object.assign(metrics, sourceRisk as Record<string, unknown>);
  }

  return {
    metrics,
    composite_risk_score: composite,
    risk_flags: safeArray<string>(data.risk_flags),
    engine: "RiskEngine",
  };
}

function ensureScenarioForecast(
  scenarios: ScenarioForecast | null | undefined,
  structured: StructuredForecastSections | null | undefined,
): ScenarioForecast {
  if (!scenarios || typeof scenarios !== "object") return buildScenarios(structured);
  return {
    scenarios: safeArray<ScenarioForecastItem>(scenarios.scenarios),
    dispersion: safeNumber(scenarios.dispersion, 0),
    engine: scenarios.engine ?? "ScenarioEngine",
  };
}

function ensureRiskForecast(
  risk: RiskForecast | null | undefined,
  data: ForecastData,
  hierarchy: ForecastHierarchyOutput | null,
): RiskForecast {
  if (!risk || typeof risk !== "object") return buildRisk(data, hierarchy);
  const mergedMetrics = {
    ...buildRisk(data, hierarchy).metrics,
    ...(risk.metrics && typeof risk.metrics === "object" ? risk.metrics : {}),
  } as RiskForecast["metrics"];
  return {
    metrics: mergedMetrics,
    composite_risk_score: safeNumber(
      risk.composite_risk_score ?? mergedMetrics.composite_risk_score,
      compositeRiskFromData(data),
    ),
    risk_flags: safeArray<string>(risk.risk_flags?.length ? risk.risk_flags : data.risk_flags),
    engine: risk.engine ?? "RiskEngine",
  };
}

function ensureActionForecast(
  action: ActionForecast | null | undefined,
  data: ForecastData,
  risk: RiskForecast,
): ActionForecast {
  if (!action || typeof action !== "object") return inferAction(data, risk);
  const recommendation = String(action.recommendation ?? "hold") as ActionRecommendation;
  return {
    recommendation,
    label_ru: action.label_ru ?? ACTION_LABELS_RU[recommendation] ?? recommendation,
    reason: action.reason ?? "",
    engine: action.engine ?? "ActionForecastEngine",
  };
}

function inferAction(data: ForecastData, risk: RiskForecast): ActionForecast {
  const riskScore = compositeRiskFromData(data);
  const confidence = safeNumber(data.calibrated_confidence ?? data.confidence, 0);
  const volExpansion = safeNumber(data.probability_map?.volatility_expansion_probability, 0);
  const liquidity = safeNumber(data.probability_map?.liquidity_deterioration_score, 0);

  let recommendation: ActionRecommendation = "hold";
  let reason = "Риск и уверенность в допустимых пределах.";

  if (riskScore >= 0.7 || volExpansion >= 0.6) {
    recommendation = "avoid";
    reason = `Композитный риск ${pct(riskScore)}, расширение волатильности ${pct(volExpansion)}.`;
  } else if (liquidity >= 0.55) {
    recommendation = "wait";
    reason = `Ликвидность ухудшается (${pct(liquidity)}) — вход лучше отложить.`;
  } else if (riskScore >= 0.55) {
    recommendation = "reduce_size";
    reason = `Композитный риск ${pct(riskScore)} выше комфортного порога.`;
  } else if (confidence >= 0.6 && riskScore <= 0.4) {
    recommendation = "enter_small_size";
    reason = `Уверенность ${pct(confidence)} при умеренном риске ${pct(riskScore)}.`;
  } else if (confidence < 0.45) {
    recommendation = "wait";
    reason = `Низкая калиброванная уверенность (${pct(confidence)}).`;
  } else if (risk.risk_flags?.includes("tail_risk")) {
    recommendation = "hedge";
    reason = "Активен tail risk — рассмотрите хедж.";
  }

  return {
    recommendation,
    label_ru: ACTION_LABELS_RU[recommendation],
    reason,
    engine: "ActionForecastEngine",
  };
}

function buildGlobalRegime(data: ForecastData, structured: StructuredForecastSections | null | undefined): RegimeContext | null {
  const hierarchy = extractHierarchy(data);
  if (hierarchy?.global_regime) return hierarchy.global_regime;

  const regimeSection = asRegimeSection(structured?.regime_forecast);
  const dominant = data.dominant_regime ?? regimeSection?.dominant_regime;
  if (!dominant) return null;

  const distribution =
    regimeSection?.distribution ??
    Object.entries(data.regime_distribution ?? {}).map(([regime, probability]) => ({
      label: regime,
      label_ru: regimeLabelRu(regime),
      probability,
      engine: "RegimeEngine",
    }));

  return {
    dominant_regime: dominant,
    dominant_regime_ru: regimeSection?.dominant_regime_ru ?? regimeLabelRu(dominant),
    confidence: regimeSection?.confidence ?? data.confidence,
    distribution,
    engine: regimeSection?.engine ?? "GlobalRegimeEngine",
  };
}

function buildSectorRegime(
  data: ForecastData,
  structured: StructuredForecastSections | null | undefined,
): RegimeContext | null {
  const hierarchy = extractHierarchy(data);
  if (hierarchy?.sector_regime) return hierarchy.sector_regime;

  const opportunities = structured?.sector_opportunities ?? [];
  const risks = structured?.sector_risks ?? [];
  if (!opportunities.length && !risks.length) return null;

  const items = [...opportunities, ...risks];
  const top = [...items].sort((a, b) => b.probability - a.probability)[0];
  const avgConf =
    items.reduce((sum, item) => sum + item.probability, 0) / Math.max(items.length, 1);

  return {
    dominant_regime: top?.label ?? "sector_mixed",
    dominant_regime_ru: top?.label_ru ?? "Секторный режим",
    confidence: avgConf,
    distribution: items.map((item) => ({
      label: item.label,
      label_ru: item.label_ru,
      probability: item.probability,
      engine: item.engine,
      high_confidence: item.high_confidence,
    })),
    engine: "SectorRegimeEngine",
  };
}

function collectNarratorInsights(
  data: ForecastData,
  structured: StructuredForecastSections | null | undefined,
  action: ActionForecast,
): string[] {
  const hierarchy = extractHierarchy(data);
  const insights: string[] = [];
  if (structured?.actionable_summary?.length) {
    insights.push(...structured.actionable_summary);
  }
  if (hierarchy?.narrator_insights?.length) insights.push(...hierarchy.narrator_insights);
  if (data.narrator_insights?.length) insights.push(...data.narrator_insights);
  if (data.forecast_explanation) insights.push(data.forecast_explanation);
  if (data.risk_explanation) insights.push(data.risk_explanation);
  if (action.reason) {
    insights.push(`${action.label_ru}: ${action.reason}`);
  }
  return [...new Set(insights)].slice(0, 8);
}

function collectHighConfidence(
  structured: StructuredForecastSections | null | undefined,
): ForecastPredictionItem[] {
  const fromStructured = structured?.high_confidence_predictions ?? [];
  return fromStructured.filter(
    (item) => (item.high_confidence ?? item.probability) >= HIGH_CONFIDENCE_THRESHOLD,
  );
}

function buildInstructionBlock(action: ActionForecast, data: ForecastData): ForecastInstructionBlock {
  const headline =
    action.label_ru ?? ACTION_LABELS_RU[action.recommendation] ?? "Удержание";
  const bodyParts = [action.reason].filter(Boolean);
  if (data.forecast_explanation) bodyParts.unshift(data.forecast_explanation);
  return {
    headline_ru: headline,
    body_ru: bodyParts.join(" ") || "Следуйте рекомендации с учётом текущего риска и уверенности модели.",
    action_recommendation: action.recommendation,
    action_label_ru: action.label_ru,
  };
}

function parseInstructionBlock(
  raw: unknown,
  action: ActionForecast,
  data: ForecastData,
): ForecastInstructionBlock {
  if (typeof raw === "string" && raw.trim()) {
    return {
      headline_ru: action.label_ru ?? ACTION_LABELS_RU[action.recommendation] ?? "Рекомендация",
      body_ru: raw.trim(),
      action_recommendation: action.recommendation,
      action_label_ru: action.label_ru,
    };
  }
  if (raw && typeof raw === "object" && "headline_ru" in raw) {
    const block = raw as ForecastInstructionBlock;
    return {
      headline_ru: block.headline_ru ?? action.label_ru ?? "Рекомендация",
      body_ru: block.body_ru ?? "",
      action_recommendation: block.action_recommendation ?? action.recommendation,
      action_label_ru: block.action_label_ru ?? action.label_ru,
    };
  }
  return buildInstructionBlock(action, data);
}

const LAYER_LABELS_RU: Record<LayerBasis["layer"], string> = {
  point: "Point Forecast",
  interval: "Interval",
  distribution: "Distribution",
  scenario: "Scenario",
  risk: "Risk",
  action: "Action",
};

function parseBasisBlock(
  raw: unknown,
  view: Omit<
    ForecastHierarchyView,
    | "instruction_block"
    | "layer_basis"
    | "scenario_archetypes"
    | "risk_engine_summary"
    | "prediction_system_summary"
  >,
  data: ForecastData,
): LayerBasis[] {
  if (Array.isArray(raw) && raw.length > 0) {
    return raw.map((block, index) => {
      const layer = (block?.layer ?? "point") as LayerBasis["layer"];
      return {
        layer,
        label_ru: LAYER_LABELS_RU[layer] ?? String(layer),
        basis_ru: String(block?.conclusion_ru ?? block?.basis_ru ?? ""),
        engine: String(block?.engine ?? "ForecastEngine"),
        confidence: block?.confidence != null ? safeNumber(block.confidence) : null,
      };
    });
  }
  return buildLayerBasis(view, data);
}

function buildLayerBasis(
  view: Omit<
    ForecastHierarchyView,
    | "instruction_block"
    | "layer_basis"
    | "scenario_archetypes"
    | "risk_engine_summary"
    | "prediction_system_summary"
  >,
  data: ForecastData,
): LayerBasis[] {
  return [
    {
      layer: "point",
      label_ru: "Point Forecast",
      basis_ru: `Momentum ${pct(view.point_forecast.confidence ?? 0.5)} · ${view.point_forecast.magnitude_ru ?? view.point_forecast.magnitude}`,
      engine: view.point_forecast.engine,
      confidence: view.point_forecast.confidence,
    },
    {
      layer: "interval",
      label_ru: "Interval",
      basis_ru: `${view.interval_forecast.horizon_ru ?? view.interval_forecast.horizon}: P10 ${formatReturn(view.interval_forecast.p10, view.interval_forecast.unit)} · P90 ${formatReturn(view.interval_forecast.p90, view.interval_forecast.unit)}`,
      engine: view.interval_forecast.engine,
      confidence: view.calibrated_confidence,
    },
    {
      layer: "distribution",
      label_ru: "Distribution",
      basis_ru: `Медиана P50 ${formatReturn(view.distribution_forecast.p50, view.distribution_forecast.unit)} · размах P5–P95`,
      engine: view.distribution_forecast.engine,
      confidence: view.calibrated_confidence,
    },
    {
      layer: "scenario",
      label_ru: "Scenario",
      basis_ru: `Dispersion ${pct(view.scenario_forecast.dispersion)} · ${safeArray(view.scenario_forecast.scenarios).length} сценариев`,
      engine: view.scenario_forecast.engine,
      confidence: safeArray<ScenarioForecastItem>(view.scenario_forecast.scenarios)[0]?.probability,
    },
    {
      layer: "risk",
      label_ru: "Risk",
      basis_ru: data.risk_explanation ?? `Композитный риск ${pct(view.risk_forecast.composite_risk_score ?? data.composite_risk_score)}`,
      engine: view.risk_forecast.engine,
      confidence: view.risk_forecast.composite_risk_score,
    },
    {
      layer: "action",
      label_ru: "Action",
      basis_ru: view.action_forecast.reason ?? "Правила Action Forecast Engine",
      engine: view.action_forecast.engine,
      confidence: view.calibrated_confidence,
    },
  ];
}

function isScenarioArchetype(value: string | undefined): value is ScenarioArchetype {
  return (
    value === "pessimistic" ||
    value === "realistic" ||
    value === "optimistic" ||
    value === "classic"
  );
}

const NARRATIVE_ARCHETYPES: ScenarioArchetype[] = [
  "pessimistic",
  "realistic",
  "optimistic",
  "classic",
];

function computeDynamicArchetypeProbabilities(
  distribution: DistributionForecast,
  momentum: number,
  volExpansion: number,
): Record<ScenarioArchetype, number> {
  const bearish = Math.max(0, 0.5 - momentum) * 2;
  const bullish = Math.max(0, momentum - 0.5) * 2;
  const spread = Math.abs(distribution.p75 - distribution.p25);

  const raw: Record<ScenarioArchetype, number> = {
    pessimistic: 0.08 + volExpansion * 0.35 + bearish * 0.25 + Math.max(0, -distribution.p5) * 2,
    realistic: 0.22 + (1 - Math.abs(momentum - 0.5) * 2) * 0.28 + spread * 0.4,
    optimistic: 0.08 + (1 - volExpansion) * 0.25 + bullish * 0.25 + Math.max(0, distribution.p75) * 2,
    classic: 0.10 + (1 - volExpansion) * 0.15 + Math.abs(distribution.p50) * 0.35,
  };

  const total = NARRATIVE_ARCHETYPES.reduce((sum, key) => sum + raw[key], 0);
  const normalized = {} as Record<ScenarioArchetype, number>;
  for (const key of NARRATIVE_ARCHETYPES) {
    normalized[key] = total > 0 ? raw[key] / total : 0.25;
  }
  return normalized;
}

function normalizeArchetypeProbabilities(items: ScenarioForecastItem[]): ScenarioForecastItem[] {
  const total = items.reduce((sum, item) => sum + item.probability, 0);
  if (total <= 0 || Math.abs(total - 1) < 0.02) return items;
  return items.map((item) => ({ ...item, probability: item.probability / total }));
}

function inferArchetype(name: string, impact: number | null | undefined, index: number): ScenarioArchetype {
  const lower = name.toLowerCase();
  if (lower.includes("pessim") || lower.includes("tail") || lower.includes("crash") || lower.includes("bear")) {
    return "pessimistic";
  }
  if (lower.includes("optim") || lower.includes("bull") || lower.includes("rally")) {
    return "optimistic";
  }
  if (lower.includes("classic") || lower.includes("baseline") || lower.includes("base")) {
    return "classic";
  }
  if (lower.includes("real") || lower.includes("central") || lower.includes("median")) {
    return "realistic";
  }
  if (impact != null && impact < 0) return "pessimistic";
  if (impact != null && impact > 0) return "optimistic";
  const order: ScenarioArchetype[] = ["pessimistic", "realistic", "optimistic", "classic"];
  return order[index % order.length];
}

function buildScenarioArchetypes(
  scenarios: ScenarioForecastItem[],
  distribution: DistributionForecast,
  momentum = 0.5,
  volExpansion = 0,
): ScenarioForecastItem[] {
  const narrativeOnly = scenarios.filter(
    (scenario) =>
      isScenarioArchetype(scenario.archetype) ||
      isScenarioArchetype(scenario.name) ||
      isScenarioArchetype(String(scenario.name).toLowerCase()),
  );

  const mapped = (narrativeOnly.length ? narrativeOnly : scenarios).map((scenario, index) => ({
    ...scenario,
    archetype:
      scenario.archetype ??
      (isScenarioArchetype(scenario.name) ? scenario.name : undefined) ??
      inferArchetype(scenario.name, scenario.impact, index),
    label_ru:
      scenario.label_ru ??
      SCENARIO_ARCHETYPE_RU[
        scenario.archetype ??
          (isScenarioArchetype(scenario.name) ? scenario.name : inferArchetype(scenario.name, scenario.impact, index))
      ],
  }));

  const byArchetype = new Map<ScenarioArchetype, ScenarioForecastItem>();
  for (const item of mapped) {
    if (!isScenarioArchetype(item.archetype)) continue;
    const key = item.archetype;
    const existing = byArchetype.get(key);
    if (!existing || item.probability > existing.probability) {
      byArchetype.set(key, item);
    }
  }

  const dynamicFallback = computeDynamicArchetypeProbabilities(distribution, momentum, volExpansion);
  const fallbackImpacts: Record<ScenarioArchetype, number> = {
    pessimistic: distribution.p5,
    realistic: distribution.p50,
    optimistic: distribution.p75,
    classic: distribution.p50,
  };

  const filled = NARRATIVE_ARCHETYPES.map((archetype) => {
    const existing = byArchetype.get(archetype);
    if (existing) return existing;
    return {
      name: archetype,
      label_ru: SCENARIO_ARCHETYPE_RU[archetype],
      probability: dynamicFallback[archetype],
      impact: fallbackImpacts[archetype],
      engine: "ScenarioEngine",
      archetype,
    };
  });

  return normalizeArchetypeProbabilities(filled);
}

type ScenarioSummaryRow = {
  key: string;
  label: string;
  probability: number;
  impact?: number | null;
};

/** Statistically describe top scenario(s) from computed probabilities. */
export function describeTopScenarios(
  scenarios: ScenarioSummaryRow[],
  options?: {
    contextPrefix?: string;
    closeThreshold?: number;
  },
): string {
  if (!scenarios.length) return "";

  const closeThreshold = options?.closeThreshold ?? CLOSE_SCENARIO_THRESHOLD;
  const ranked = [...scenarios].sort((a, b) => b.probability - a.probability);
  const top = ranked[0];
  const topImpact =
    top.impact != null && Number.isFinite(top.impact)
      ? `, ожидаемый эффект ${formatReturn(top.impact, "return")}`
      : "";

  const parts = [
    `Наиболее вероятный сценарий — «${top.label}» (${pct(top.probability)}${topImpact}).`,
  ];

  if (ranked.length >= 2) {
    const second = ranked[1];
    const diff = top.probability - second.probability;
    if (diff < closeThreshold) {
      const secondImpact =
        second.impact != null && Number.isFinite(second.impact)
          ? `, эффект ${formatReturn(second.impact, "return")}`
          : "";
      parts.push(
        `Второй по вероятности — «${second.label}» (${pct(second.probability)}${secondImpact}); ` +
          `разрыв ${pct(diff)} — исходы статистически близки.`,
      );
    }
  }

  const body = parts.join(" ");
  return options?.contextPrefix ? `${options.contextPrefix} ${body}` : body;
}

function buildRiskEngineSummary(data: ForecastData, risk: RiskForecast): string[] {
  const lines: string[] = [];
  if (data.risk_explanation) lines.push(data.risk_explanation);
  lines.push(`Композитный риск инструмента: ${pct(risk.composite_risk_score ?? data.composite_risk_score)}.`);
  if (risk.risk_flags?.length) {
    lines.push(`Активные флаги: ${risk.risk_flags.slice(0, 4).map((f) => f.replace(/_/g, " ")).join(", ")}.`);
  }
  const vol =
    risk.metrics?.volatility_expansion_probability ??
    data.probability_map?.volatility_expansion_probability;
  if (vol != null && Number.isFinite(Number(vol))) {
    lines.push(`Вероятность расширения волатильности: ${pct(Number(vol))}.`);
  }
  return lines.slice(0, 4);
}

function buildPredictionSystemSummary(
  data: ForecastData,
  view: Omit<
    ForecastHierarchyView,
    | "instruction_block"
    | "layer_basis"
    | "scenario_archetypes"
    | "risk_engine_summary"
    | "prediction_system_summary"
  >,
  scenarioArchetypes: ScenarioForecastItem[],
): string[] {
  const hierarchyRaw = (data.hierarchy_output ??
    data.hierarchy ??
    data.forecast_output) as Record<string, unknown> | null | undefined;
  const report = hierarchyRaw?.prediction_system_report as Record<string, unknown> | undefined;
  const apiSummary =
    typeof report?.general_summary === "string" ? report.general_summary.trim() : "";

  const scenarioRows: ScenarioSummaryRow[] = scenarioArchetypes.map((item) => ({
    key: String(item.archetype ?? item.name),
    label: item.label_ru ?? item.name,
    probability: safeNumber(item.probability, 0),
    impact: item.impact,
  }));

  const computedSummary =
    apiSummary ||
    describeTopScenarios(scenarioRows, {
      contextPrefix: view.symbol ? `По ${view.symbol}:` : undefined,
    });

  const lines: string[] = [];
  if (computedSummary) lines.push(computedSummary);
  lines.push(`Калиброванная уверенность прогноза: ${pct(view.calibrated_confidence)}.`);
  if (view.global_regime) {
    lines.push(
      `Макро-режим: ${regimeLabelRu(view.global_regime.dominant_regime, view.global_regime.dominant_regime_ru)} (${pct(view.global_regime.confidence)}).`,
    );
  }
  return [...new Set(lines)].slice(0, 4);
}

/** Build 3 expandable market outlook cards from GET /forecast/market payload. */
export function buildMarketOutlookCards(market: MarketForecastData | null | undefined): MarketOutlookCard[] {
  if (!market || typeof market !== "object") return [];

  const cardsFromApi = safeArray<MarketOutlookCard>(market.market_outlook_cards);
  if (cardsFromApi.length) {
    return cardsFromApi.slice(0, 3).map((card, index) => ({
      id: card.id ?? `outlook-${index}`,
      title_ru: card.title_ru ?? DEFAULT_OUTLOOK_TITLES[index] ?? `Outlook ${index + 1}`,
      summary: typeof card.summary === "string" ? card.summary : outlookEntrySummary(card.summary),
      evidence_basis: safeArray<string>(card.evidence_basis),
      confidence: safeNumber(card.confidence, 0.5),
      engine: card.engine ?? "ForecastEngine",
    }));
  }

  const global = (market.global_regime ?? {}) as Record<string, unknown>;
  const confidence = safeNumber(global.confidence, 0.5);
  const cards: MarketOutlookCard[] = [];
  const outlookLines = safeArray<MarketOutlookEntry>(market.market_outlook);

  for (let i = 0; i < Math.min(3, outlookLines.length); i++) {
    const entry = outlookLines[i];
    const point = isMarketOutlookPoint(entry) ? entry : null;
    const evidence: string[] = safeArray<string>(point?.evidence_basis);

    if (i === 0 && global.dominant_regime_ru) {
      evidence.push(`Доминирующий режим: ${String(global.dominant_regime_ru)}`);
      const dist = global.distribution as Record<string, number> | undefined;
      if (dist && typeof dist === "object") {
        const top = Object.entries(dist).sort((a, b) => b[1] - a[1])[0];
        if (top) evidence.push(`${top[0]}: ${pct(top[1])}`);
      }
    }
    if (i === 1) {
      const vix = market.macro_indicators?.vix;
      if (vix != null) evidence.push(`VIX: ${Number(vix).toFixed(1)}`);
      const riskOff = market.calibrated_probabilities?.risk_off;
      if (riskOff != null) evidence.push(`Risk-off: ${pct(riskOff)}`);
    }
    if (i === 2 && safeArray(market.sector_rotation).length) {
      const leader = market.sector_rotation[0] as Record<string, unknown>;
      evidence.push(
        `Лидер: ${String(leader.sector_ru ?? leader.sector ?? "—")} (${String(leader.rotation_flag_ru ?? leader.rotation_flag ?? "")})`,
      );
    }

    const pointConfidence =
      point?.confidence_pct != null ? clamp01(point.confidence_pct / 100) : null;

    cards.push({
      id: `outlook-${i}`,
      title_ru: outlookEntryTitle(entry, i),
      summary: outlookEntrySummary(entry),
      evidence_basis: evidence.length ? evidence : ["Forecast Engine aggregate"],
      confidence: pointConfidence ?? (i === 0 ? confidence : Math.max(0.35, confidence - i * 0.08)),
      engine: i === 0 ? "GlobalRegimeEngine" : i === 1 ? "RiskEngine" : "SectorRegimeEngine",
    });
  }

  while (cards.length < 3 && outlookLines.length > cards.length) {
    const idx = cards.length;
    const entry = outlookLines[idx];
    cards.push({
      id: `outlook-${idx}`,
      title_ru: outlookEntryTitle(entry, idx),
      summary: outlookEntrySummary(entry),
      evidence_basis: ["Market forecast aggregate"],
      confidence: Math.max(0.3, confidence - idx * 0.1),
      engine: "ForecastEngine",
    });
  }

  return cards.slice(0, 3);
}

/** Normalize API payload into a full 6-layer view (scaffold + live hierarchy when present). */
export function normalizeForecastHierarchy(data: ForecastData | null | undefined): ForecastHierarchyView {
  const safeData: ForecastData = {
    symbol: data?.symbol ?? "—",
    instrument_id: data?.instrument_id ?? 0,
    dominant_regime: data?.dominant_regime ?? null,
    regime_distribution: data?.regime_distribution ?? {},
    composite_risk_score: compositeRiskFromData(data ?? ({} as ForecastData)),
    confidence: safeNumber(data?.confidence, 0),
    calibrated_confidence: data?.calibrated_confidence,
    risk_flags: safeArray(data?.risk_flags),
    factor_exposures: data?.factor_exposures ?? {},
    probability_map: data?.probability_map ?? {},
    metric_validity: data?.metric_validity ?? {},
    data_quality: data?.data_quality ?? {},
    forecast_explanation: data?.forecast_explanation ?? null,
    regime_explanation: data?.regime_explanation ?? null,
    risk_explanation: data?.risk_explanation ?? null,
    risk_engine_metrics: data?.risk_engine_metrics ?? {},
    source_metrics: data?.source_metrics ?? {},
    structured: data?.structured ?? null,
    as_of: data?.as_of ?? null,
    snapshot_id: data?.snapshot_id ?? null,
    hierarchy: data?.hierarchy ?? null,
    forecast_output: data?.forecast_output ?? null,
    hierarchy_output: data?.hierarchy_output ?? null,
    action_recommendation: data?.action_recommendation ?? null,
    narrator_insights: safeArray(data?.narrator_insights),
  };

  const hierarchy = extractHierarchy(safeData);
  const hierarchyRaw = (safeData.hierarchy_output ??
    safeData.hierarchy ??
    safeData.forecast_output) as Record<string, unknown> | null | undefined;
  const structured = safeData.structured ?? null;
  const momentum = momentumFromData(safeData);
  const volExpansion = volExpansionFromData(safeData, hierarchy);

  const interval =
    hierarchy?.interval_forecast ??
    buildInterval(safeData, volExpansion);
  const distribution =
    hierarchy?.distribution_forecast ??
    buildDistribution(interval, momentum);
  const scenarios = ensureScenarioForecast(
    hierarchy?.scenario_forecast ?? null,
    structured,
  );
  const risk = ensureRiskForecast(hierarchy?.risk_forecast ?? null, safeData, hierarchy);
  const action = ensureActionForecast(hierarchy?.action_forecast ?? null, safeData, risk);

  const partial = {
    symbol: safeData.symbol,
    as_of: hierarchy?.as_of ?? safeData.as_of ?? null,
    calibrated_confidence: safeNumber(
      hierarchy?.calibrated_confidence ?? safeData.calibrated_confidence ?? safeData.confidence,
      0,
    ),
    global_regime: buildGlobalRegime(safeData, structured),
    sector_regime: buildSectorRegime(safeData, structured),
    point_forecast: hierarchy?.point_forecast ?? momentumToPoint(momentum),
    interval_forecast: interval,
    distribution_forecast: distribution,
    scenario_forecast: scenarios,
    risk_forecast: risk,
    action_forecast: action,
    narrator_insights: collectNarratorInsights(safeData, structured, action),
    high_confidence_predictions: collectHighConfidence(structured),
    engines_used: safeArray<string>(structured?.engines_used).length
      ? safeArray<string>(structured?.engines_used)
      : [
          "PredictionHierarchyOrchestrator",
          "RegimeEngine",
          "ForecastEngine",
          "RiskEngine",
          "ScenarioEngine",
          "ActionForecastEngine",
        ],
    from_hierarchy_api: Boolean(
      hierarchy?.point_forecast ||
        hierarchy?.action_forecast ||
        hierarchy?.global_regime,
    ),
    metric_validity: safeData.metric_validity ?? {},
    data_quality: safeData.data_quality ?? parseDataQuality(safeData.probability_map),
  };

  const scenarioArchetypes = buildScenarioArchetypes(
    safeArray(scenarios.scenarios),
    distribution,
    momentum,
    volExpansion,
  );

  return {
    ...partial,
    instruction_block: parseInstructionBlock(hierarchyRaw?.instruction_block, action, safeData),
    layer_basis: parseBasisBlock(hierarchyRaw?.basis_block, partial, safeData),
    scenario_archetypes: scenarioArchetypes,
    risk_engine_summary: buildRiskEngineSummary(safeData, risk),
    prediction_system_summary: buildPredictionSystemSummary(safeData, partial, scenarioArchetypes),
  };
}

export function formatReturn(value: number, unit?: string): string {
  if (unit === "return") {
    const pctVal = value * 100;
    return `${pctVal >= 0 ? "+" : ""}${pctVal.toFixed(1)}%`;
  }
  return value.toFixed(2);
}

export function riskMetricTone(value: number): "ok" | "caution" | "block" {
  if (value >= 0.65) return "block";
  if (value >= 0.4) return "caution";
  return "ok";
}

export function actionTone(
  recommendation: ActionRecommendation,
): "neutral" | "positive" | "caution" | "block" {
  switch (recommendation) {
    case "enter_normal_size":
    case "enter_small_size":
    case "hold":
      return "positive";
    case "hedge":
    case "reduce_size":
    case "wait":
      return "caution";
    case "avoid":
      return "block";
    default:
      return "neutral";
  }
}
