"use client";

import { useState } from "react";
import { format, parseISO } from "date-fns";
import { ru } from "date-fns/locale";
import { clsx } from "clsx";
import Link from "next/link";
import { AlertTriangle, ArrowDown, ArrowRight, ArrowUp, Gauge, HelpCircle, MessageSquare, Minus, Shield, Sparkles, Target } from "lucide-react";
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ForecastHierarchyView, LayerBasis } from "@/types";
import { CockpitPanelHeader } from "@/components/operator/CockpitPanelHeader";
import { readChartColors } from "@/lib/chartColors";
import {
  ACTION_LABELS_RU,
  FORECAST_DISCLAIMER,
  LAYER_TOOLTIPS_RU,
  actionTone,
  engineLabel,
  formatReturn,
  pct,
  regimeLabelRu,
  riskMetricTone,
} from "@/lib/forecast-hierarchy";

interface AssetCockpitPredictionPanelProps {
  view: ForecastHierarchyView;
  livePrice?: number | null;
  symbol?: string;
  className?: string;
  /** Forecasting page hides regime/action/instruction extras. */
  variant?: "full" | "forecasting";
}

function ProvenanceBadge({ engine }: { engine: string }) {
  return (
    <span className="text-[9px] uppercase tracking-wide text-accent/90 bg-cockpit-panel border border-primary/30 px-1.5 py-0.5 rounded">
      {engineLabel(engine)}
    </span>
  );
}

function LayerTooltip({ layerKey }: { layerKey: keyof typeof LAYER_TOOLTIPS_RU }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-flex">
      <button
        type="button"
        className="text-qa-muted hover:text-qa-text transition-colors"
        aria-label="Подсказка"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >
        <HelpCircle size={12} />
      </button>
      {open && (
        <span className="absolute z-20 left-0 top-full mt-1 w-52 rounded-md border border-cockpit-border bg-cockpit-panel-raised px-2 py-1.5 text-[10px] leading-snug text-qa-text shadow-dark">
          {LAYER_TOOLTIPS_RU[layerKey]}
        </span>
      )}
    </span>
  );
}

function LayerCard({
  title,
  layerKey,
  subtitle,
  engine,
  basis,
  children,
  className,
}: {
  title: string;
  layerKey: keyof typeof LAYER_TOOLTIPS_RU;
  subtitle?: string;
  engine: string;
  basis?: LayerBasis;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={clsx("cockpit-panel flex flex-col min-h-0", className)}>
      <CockpitPanelHeader
        title={
          <span className="inline-flex items-center gap-1.5">
            {title}
            <LayerTooltip layerKey={layerKey} />
          </span>
        }
        subtitle={subtitle}
      />
      <div className="p-3 space-y-2 flex-1">{children}</div>
      {basis && (
        <div className="px-3 pb-2 text-[10px] text-qa-muted border-t border-cockpit-border/60 pt-2 leading-relaxed">
          <span className="text-qa-muted uppercase tracking-wide text-[9px]">Basis · </span>
          {basis.basis_ru}
        </div>
      )}
      <div className="px-3 pb-2 pt-1 border-t border-cockpit-border/60">
        <ProvenanceBadge engine={engine} />
      </div>
    </div>
  );
}

function PointDirectionIcon({ direction }: { direction: "up" | "down" | "neutral" }) {
  if (direction === "up") return <ArrowUp size={28} className="text-terminal-up" />;
  if (direction === "down") return <ArrowDown size={28} className="text-terminal-down" />;
  return <Minus size={28} className="text-qa-muted" />;
}

function ActionBadge({ view }: { view: ForecastHierarchyView }) {
  const action = view.action_forecast;
  const tone = actionTone(action.recommendation);
  const toneClass =
    tone === "positive"
      ? "bg-qa-success-bg border-terminal-up/40 text-terminal-up"
      : tone === "caution"
      ? "bg-[var(--qa-active)] border-terminal-accent/40 text-terminal-accent"
      : tone === "block"
      ? "bg-qa-danger-bg border-terminal-down/40 text-terminal-down"
      : "bg-cockpit-panel-raised border-cockpit-border text-qa-text";

  return (
    <div className={clsx("rounded-lg border px-4 py-3", toneClass)}>
      <div className="text-[10px] uppercase tracking-wide opacity-80 mb-1">Рекомендация</div>
      <div className="text-xl font-bold">
        {action.label_ru ?? ACTION_LABELS_RU[action.recommendation]}
      </div>
      {action.reason && (
        <p className="text-[11px] leading-relaxed mt-2 opacity-90">{action.reason}</p>
      )}
    </div>
  );
}

function RegimeStrip({
  title,
  regime,
}: {
  title: string;
  regime: NonNullable<ForecastHierarchyView["global_regime"]>;
}) {
  return (
    <div className="rounded-lg bg-cockpit-panel-raised border border-cockpit-border p-3">
      <div className="flex items-center gap-2 text-[10px] uppercase tracking-wide text-qa-muted mb-1">
        <Gauge size={12} />
        {title}
      </div>
      <div className="text-sm font-semibold text-white">
        {regimeLabelRu(regime.dominant_regime, regime.dominant_regime_ru)}
      </div>
      <div className="text-[11px] text-qa-muted mt-1 tabular-nums">
        Уверенность {pct(regime.confidence)}
      </div>
      {regime.distribution && regime.distribution.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {regime.distribution.slice(0, 4).map((item, index) => (
            <span
              key={`${item.label ?? item.label_ru}-${index}`}
              className="text-[9px] px-1.5 py-0.5 rounded border border-cockpit-border bg-cockpit-bg tabular-nums"
            >
              {(item.label_ru ?? item.label ?? "regime").slice(0, 28)} · {pct(item.probability)}
            </span>
          ))}
        </div>
      )}
      <div className="mt-2">
        <ProvenanceBadge engine={regime.engine} />
      </div>
    </div>
  );
}

function RiskMetricRow({
  label,
  value,
  invalid,
}: {
  label: string;
  value: number;
  invalid?: boolean;
}) {
  if (invalid) {
    return (
      <div>
        <div className="flex justify-between text-[11px] mb-1">
          <span className="text-qa-muted capitalize">{label.replace(/_/g, " ")}</span>
          <span className="font-mono tabular-nums text-qa-muted">н/д</span>
        </div>
        <p className="text-[10px] text-qa-muted">недостаточно данных</p>
      </div>
    );
  }
  const tone = riskMetricTone(value);
  const color =
    tone === "block" ? "bg-terminal-down" : tone === "caution" ? "bg-terminal-accent" : "bg-terminal-up";
  return (
    <div>
      <div className="flex justify-between text-[11px] mb-1">
        <span className="text-qa-muted capitalize">{label.replace(/_/g, " ")}</span>
        <span className="font-mono tabular-nums text-qa-text">{pct(value)}</span>
      </div>
      <div className="h-1.5 bg-cockpit-bg rounded-full overflow-hidden">
        <div className={clsx("h-full rounded-full", color)} style={{ width: `${value * 100}%` }} />
      </div>
    </div>
  );
}

function EngineSection({
  title,
  lines,
  badgeEngine,
  accent,
}: {
  title: string;
  lines: string[];
  badgeEngine: string;
  accent: "risk" | "prediction";
}) {
  const borderClass =
    accent === "risk" ? "border-status-block/40 bg-status-block/10" : "border-primary/30 bg-primary/10";
  return (
    <div className={clsx("cockpit-panel border", borderClass)}>
      <CockpitPanelHeader title={title} />
      <ul className="p-3 space-y-2">
        {lines.map((line, index) => (
          <li key={`${index}-${line.slice(0, 20)}`} className="text-[11px] text-qa-text leading-relaxed flex gap-2">
            <ArrowRight size={10} className={accent === "risk" ? "text-status-block" : "text-primary"} />
            <span>{line}</span>
          </li>
        ))}
      </ul>
      <div className="px-3 pb-2">
        <ProvenanceBadge engine={badgeEngine} />
      </div>
    </div>
  );
}

function formatAsOf(asOf: string | null): string {
  if (!asOf) return "ежедневное обновление";
  try {
    return format(parseISO(asOf), "dd MMM yyyy, HH:mm", { locale: ru });
  } catch {
    return asOf;
  }
}

export function AssetCockpitPredictionPanel({
  view,
  livePrice,
  symbol,
  className,
  variant = "full",
}: AssetCockpitPredictionPanelProps) {
  const isForecasting = variant === "forecasting";
  const instruction = view.instruction_block ?? {
    headline_ru: "—",
    body_ru: "",
    action_recommendation: "hold" as const,
  };
  const distribution = view.distribution_forecast ?? {
    p5: 0,
    p25: 0,
    p50: 0,
    p75: 0,
    p95: 0,
    engine: "ScenarioEngine",
  };
  const interval = view.interval_forecast ?? {
    p10: 0,
    p90: 0,
    horizon: "5D",
    engine: "RiskEngine",
  };
  const scenarioArchetypes = view.scenario_archetypes ?? [];
  const riskEngineSummary = view.risk_engine_summary ?? [];
  const predictionSystemSummary = view.prediction_system_summary ?? [];
  const narratorInsights = view.narrator_insights ?? [];
  const highConfidence = view.high_confidence_predictions ?? [];
  const enginesUsed = view.engines_used ?? [];
  const layerBasis = view.layer_basis ?? [];
  const riskMetrics = view.risk_forecast?.metrics ?? {};
  const riskFlags = view.risk_forecast?.risk_flags ?? [];
  const pointForecast = view.point_forecast ?? {
    direction: "neutral" as const,
    magnitude: "neutral" as const,
    engine: "ForecastEngine",
  };

  const distributionData = [
    { band: "P5", value: distribution.p5 ?? 0 },
    { band: "P25", value: distribution.p25 ?? 0 },
    { band: "P50", value: distribution.p50 ?? 0 },
    { band: "P75", value: distribution.p75 ?? 0 },
    { band: "P95", value: distribution.p95 ?? 0 },
  ];

  const riskNumeric = Object.entries(riskMetrics).filter(
    ([key, value]) =>
      key !== "composite_risk_score" &&
      typeof value === "number" &&
      Number.isFinite(value) &&
      value <= 1,
  ) as [string, number][];

  const intervalLow =
    livePrice != null ? livePrice * (1 + (interval.p10 ?? 0)) : null;
  const intervalHigh =
    livePrice != null ? livePrice * (1 + (interval.p90 ?? 0)) : null;

  const chartColors = readChartColors();

  const basisForLayer = (layer: LayerBasis["layer"]) =>
    layerBasis.find((item) => item.layer === layer);

  return (
    <section className={clsx("space-y-3", className)}>
      <div className="cockpit-panel">
        <CockpitPanelHeader
          title="Prediction Panel"
          subtitle={`${view.symbol} · 6 слоёв`}
          action={
            <span className="text-[10px] text-qa-muted font-normal tabular-nums">
              {formatAsOf(view.as_of)}
            </span>
          }
        />
        <div className="p-3 space-y-3">
          <div className="flex flex-wrap items-center gap-3 text-[11px]">
            <span className="text-qa-muted">
              Калиброванная уверенность{" "}
              <span className="text-white font-semibold tabular-nums">
                {pct(view.calibrated_confidence)}
              </span>
            </span>
            {view.from_hierarchy_api && (
              <span className="text-terminal-up text-[10px] uppercase tracking-wide">
                
              </span>
            )}
            <span className="text-terminal-accent/90 flex items-center gap-1 shrink-0">
              <AlertTriangle size={12} />
              {FORECAST_DISCLAIMER}
            </span>
          </div>
          <p
            role="note"
            className="text-[10px] text-terminal-accent/80 border border-terminal-accent/40 rounded px-2 py-1.5 bg-[var(--qa-active)]"
          >
            {FORECAST_DISCLAIMER}
          </p>

          {!isForecasting && (
            <>
              <div className="rounded-lg border border-primary/30 bg-primary/10 p-3">
                <div className="flex items-start gap-2">
                  <Target size={18} className="text-primary shrink-0 mt-0.5" />
                  <div>
                    <div className="text-sm font-bold text-white">{instruction.headline_ru}</div>
                    <p className="text-[11px] text-qa-text leading-relaxed mt-1">
                      {instruction.body_ru}
                    </p>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {view.global_regime && <RegimeStrip title="Макро-режим" regime={view.global_regime} />}
                {view.sector_regime && (
                  <RegimeStrip title="Секторный режим" regime={view.sector_regime} />
                )}
              </div>

              <ActionBadge view={view} />
            </>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <EngineSection
          title="What Risk Engine tells us"
          lines={riskEngineSummary.length ? riskEngineSummary : ["Risk Engine data loading…"]}
          badgeEngine="RiskEngine"
          accent="risk"
        />
        <EngineSection
          title="What Prediction System tells us"
          lines={predictionSystemSummary.length ? predictionSystemSummary : ["Prediction system data loading…"]}
          badgeEngine="ForecastEngine"
          accent="prediction"
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        <LayerCard
          title="Point"
          layerKey="point"
          subtitle="Направление"
          engine={pointForecast.engine}
          basis={basisForLayer("point")}
        >
          <div className="flex items-center gap-4">
            <PointDirectionIcon direction={pointForecast.direction ?? "neutral"} />
            <div>
              <div className="text-lg font-bold text-white">
                {pointForecast.magnitude_ru ??
                  (pointForecast.magnitude ? pointForecast.magnitude.replace(/_/g, " ") : "Нейтрально")}
              </div>
              {pointForecast.confidence != null && (
                <div className="text-[11px] text-qa-muted tabular-nums mt-1">
                  Signal {pct(pointForecast.confidence)}
                </div>
              )}
            </div>
          </div>
        </LayerCard>

        <LayerCard
          title="Interval"
          layerKey="interval"
          subtitle={interval.horizon_ru ?? interval.horizon}
          engine={interval.engine}
          basis={basisForLayer("interval")}
        >
          <div className="space-y-2 text-[11px]">
            <div className="flex justify-between">
              <span className="text-qa-muted">P10</span>
              <span className="font-mono tabular-nums text-terminal-accent">
                {formatReturn(interval.p10 ?? 0, interval.unit)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-qa-muted">P90</span>
              <span className="font-mono tabular-nums text-terminal-accent">
                {formatReturn(interval.p90 ?? 0, interval.unit)}
              </span>
            </div>
            {intervalLow != null && intervalHigh != null && (
              <div className="rounded border border-dashed border-terminal-accent/40 bg-[var(--qa-active)] px-2 py-1.5 text-[10px] text-terminal-accent/90">
                Зона на графике: {intervalLow.toFixed(2)} – {intervalHigh.toFixed(2)}
              </div>
            )}
          </div>
        </LayerCard>

        <LayerCard
          title="Distribution"
          layerKey="distribution"
          subtitle="Percentile bands"
          engine={distribution.engine}
          basis={basisForLayer("distribution")}
          className="md:col-span-2 xl:col-span-1"
        >
          <div className="h-36">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={distributionData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                <XAxis dataKey="band" tick={{ fill: chartColors.textMuted, fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis
                  tick={{ fill: chartColors.volMid, fontSize: 9 }}
                  tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  contentStyle={{
                    background: chartColors.panel,
                    border: `1px solid ${chartColors.border}`,
                    fontSize: 11,
                  }}
                  formatter={(value: number) => formatReturn(value, distribution.unit)}
                />
                <Bar dataKey="value" radius={[3, 3, 0, 0]}>
                  {distributionData.map((entry) => (
                    <Cell
                      key={entry.band}
                      fill={entry.value >= 0 ? chartColors.positiveBar : chartColors.negativeBar}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </LayerCard>

        <LayerCard
          title="Scenario"
          layerKey="scenario"
          subtitle="4 archetypes"
          engine={view.scenario_forecast?.engine ?? "ScenarioEngine"}
          basis={basisForLayer("scenario")}
          className="md:col-span-2"
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {scenarioArchetypes.map((scenario) => (
              <div
                key={`${scenario.archetype ?? scenario.name}-${scenario.engine}`}
                className="cockpit-feed-item p-2.5"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="text-[11px] text-qa-text leading-snug">
                    {scenario.label_ru ?? scenario.name}
                  </p>
                  <span className="text-sm font-bold tabular-nums text-white shrink-0">
                    {pct(scenario.probability)}
                  </span>
                </div>
                {scenario.impact != null && (
                  <p className="text-[10px] text-qa-muted mt-1 tabular-nums">
                    Impact {formatReturn(scenario.impact, "return")}
                  </p>
                )}
              </div>
            ))}
          </div>
        </LayerCard>

        <LayerCard
          title="Risk"
          layerKey="risk"
          subtitle="RiskEngine metrics"
          engine={view.risk_forecast?.engine ?? "RiskEngine"}
          basis={basisForLayer("risk")}
        >
          <div className="space-y-2.5">
            {riskNumeric.slice(0, 4).map(([key, value]) => (
              <RiskMetricRow
                key={key}
                label={key}
                value={value}
                invalid={view.metric_validity?.[key] === false}
              />
            ))}
            {riskFlags.length > 0 && (
              <div className="flex flex-wrap gap-1 pt-1">
                {riskFlags.map((flag) => (
                  <span
                    key={flag}
                    className="text-[9px] uppercase px-1.5 py-0.5 rounded border border-terminal-down/40 text-terminal-down bg-qa-danger-bg"
                  >
                    {flag.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            )}
          </div>
        </LayerCard>
      </div>

      {(narratorInsights.length > 0 || (!isForecasting && highConfidence.length > 0)) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {narratorInsights.length > 0 && (
            <div className={clsx("cockpit-panel", isForecasting && "lg:col-span-2")}>
              <CockpitPanelHeader title="Prediction Narrator" subtitle="Что это значит" />
              <ul className="p-3 space-y-2">
                {narratorInsights.map((phrase, index) => (
                  <li
                    key={`${index}-${phrase.slice(0, 24)}`}
                    className="flex gap-2 text-[11px] text-qa-text leading-relaxed"
                  >
                    <Sparkles size={12} className="text-primary shrink-0 mt-0.5" />
                    <span className="whitespace-pre-line">{phrase}</span>
                  </li>
                ))}
              </ul>
              <div className="px-3 pb-2">
                <ProvenanceBadge engine="PredictionNarrator" />
              </div>
            </div>
          )}

          {!isForecasting && highConfidence.length > 0 && (
            <div className="cockpit-panel">
              <CockpitPanelHeader
                title="Высокая уверенность"
                subtitle="≥85%"
                badge={highConfidence.length}
              />
              <ul className="p-3 space-y-2">
                {highConfidence.map((item, index) => (
                  <li key={`${item.label_ru}-${index}`} className="cockpit-feed-item p-2.5">
                    <div className="flex justify-between gap-2">
                      <span className="text-[11px] text-qa-text">
                        {item.label_ru ?? item.label}
                      </span>
                      <span className="text-sm font-bold tabular-nums text-terminal-up">
                        {pct(item.high_confidence ?? item.probability)}
                      </span>
                    </div>
                    <p className="text-[9px] text-qa-muted mt-1">{engineLabel(item.engine)}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {!isForecasting && symbol && (
        <Link
          href={`/chat?symbol=${encodeURIComponent(symbol)}`}
          className="inline-flex items-center gap-1.5 text-xs text-terminal-accent hover:text-terminal-accent px-1"
        >
          <MessageSquare size={14} />
          Обсудить прогноз
        </Link>
      )}

      {!isForecasting && (
        <div className="flex flex-wrap gap-2 text-[9px] text-qa-muted px-1">
          <Shield size={10} className="text-qa-muted" />
          {enginesUsed.map((engine) => (
            <span key={engine} className="inline-flex items-center gap-1">
              <ArrowRight size={8} />
              {engineLabel(engine)}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

export type { ForecastHierarchyView as PredictionPanelView };
