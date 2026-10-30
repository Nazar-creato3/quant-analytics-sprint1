/** 6-layer ForecastOutput hierarchy (Prompt 34/38) — mirrors backend schema when available. */

export type PointMagnitude =
  | "strong_up"
  | "up"
  | "neutral"
  | "down"
  | "strong_down";

export type ActionRecommendation =
  | "wait"
  | "reduce_size"
  | "hedge"
  | "hold"
  | "enter_small_size"
  | "enter_normal_size"
  | "avoid";

export interface ForecastPredictionItem {
  label?: string;
  label_ru?: string;
  probability: number;
  probability_pct?: number;
  engine: string;
  symbol?: string | null;
  high_confidence?: number | null;
}

export interface MarketOutlookScenario {
  scenario: string;
  label_ru?: string;
  probability: number;
  probability_pct?: number;
  engine: string;
  high_confidence?: number | null;
}

export interface RegimeForecastSection {
  dominant_regime?: string;
  dominant_regime_ru?: string;
  confidence?: number;
  distribution?: ForecastPredictionItem[];
  engine?: string;
}

export interface StructuredForecastSections {
  market_outlook?: MarketOutlookScenario[];
  sector_opportunities?: ForecastPredictionItem[];
  sector_risks?: ForecastPredictionItem[];
  regime_forecast?: RegimeForecastSection | Record<string, unknown>;
  tail_risk_events?: ForecastPredictionItem[];
  actionable_summary?: string[];
  high_confidence_predictions?: ForecastPredictionItem[];
  engines_used?: string[];
}

export interface RegimeContext {
  dominant_regime: string;
  dominant_regime_ru?: string;
  confidence: number;
  distribution?: ForecastPredictionItem[];
  engine: string;
}

export interface PointForecast {
  direction: "up" | "down" | "neutral";
  magnitude: PointMagnitude;
  magnitude_ru?: string;
  confidence?: number;
  engine: string;
}

export interface IntervalForecast {
  horizon: string;
  horizon_ru?: string;
  p10: number;
  p90: number;
  unit?: string;
  engine: string;
}

export interface DistributionForecast {
  p5: number;
  p25: number;
  p50: number;
  p75: number;
  p95: number;
  unit?: string;
  engine: string;
}

export type ScenarioArchetype = "pessimistic" | "realistic" | "optimistic" | "classic";

export interface ScenarioForecastItem {
  name: string;
  label_ru?: string;
  probability: number;
  impact?: number | null;
  engine: string;
  archetype?: ScenarioArchetype;
}

export interface LayerBasis {
  layer: "point" | "interval" | "distribution" | "scenario" | "risk" | "action";
  label_ru: string;
  basis_ru: string;
  engine: string;
  confidence?: number | null;
}

export interface ForecastInstructionBlock {
  headline_ru: string;
  body_ru: string;
  action_recommendation: ActionRecommendation;
  action_label_ru?: string;
}

/** Detailed market outlook point from GET /forecast/market (enhanced API). */
export interface MarketOutlookPoint {
  title?: string;
  what_happens?: string;
  how?: string;
  where?: string;
  expectations?: string;
  prognosis?: string;
  evidence_basis?: string[];
  confidence_pct?: number;
}

/** Legacy string bullet or enhanced object from the market forecast API. */
export type MarketOutlookEntry = string | MarketOutlookPoint;

/** Expandable market-wide outlook card (GET /forecast/market). */
export interface MarketOutlookCard {
  id: string;
  title_ru: string;
  summary: string;
  evidence_basis: string[];
  confidence: number;
  engine: string;
}

export interface ScenarioForecast {
  scenarios: ScenarioForecastItem[];
  dispersion: number;
  engine: string;
}

export interface RiskForecast {
  metrics: Record<string, number | string | boolean | null>;
  marginal_delta_var?: number | null;
  marginal_delta_es?: number | null;
  composite_risk_score?: number;
  risk_flags?: string[];
  engine: string;
}

export interface ActionForecast {
  recommendation: ActionRecommendation;
  label_ru?: string;
  reason?: string;
  engine: string;
}

/** Unified hierarchy payload from PredictionHierarchyOrchestrator (Prompt 38). */
export interface ForecastHierarchyOutput {
  point_forecast?: PointForecast | null;
  interval_forecast?: IntervalForecast | null;
  distribution_forecast?: DistributionForecast | null;
  scenario_forecast?: ScenarioForecast | null;
  risk_forecast?: RiskForecast | null;
  action_forecast?: ActionForecast | null;
  global_regime?: RegimeContext | null;
  sector_regime?: RegimeContext | null;
  calibrated_confidence?: number | null;
  narrator_insights?: string[];
  as_of?: string | null;
}

/** Normalized view model for UI rendering with guaranteed layer slots. */
export interface ForecastHierarchyView {
  symbol: string;
  as_of: string | null;
  calibrated_confidence: number;
  global_regime: RegimeContext | null;
  sector_regime: RegimeContext | null;
  point_forecast: PointForecast;
  interval_forecast: IntervalForecast;
  distribution_forecast: DistributionForecast;
  scenario_forecast: ScenarioForecast;
  risk_forecast: RiskForecast;
  action_forecast: ActionForecast;
  instruction_block: ForecastInstructionBlock;
  layer_basis: LayerBasis[];
  scenario_archetypes: ScenarioForecastItem[];
  risk_engine_summary: string[];
  prediction_system_summary: string[];
  narrator_insights: string[];
  high_confidence_predictions: ForecastPredictionItem[];
  engines_used: string[];
  from_hierarchy_api: boolean;
  metric_validity?: Record<string, boolean>;
  data_quality?: Record<string, string>;
}
