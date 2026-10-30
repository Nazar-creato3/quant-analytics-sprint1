"""Forecasting API response schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.schemas.ticker_analysis import TickerAnalysisPayload


class ForecastPredictionItem(BaseModel):
    label: str
    label_ru: str = ""
    probability: float = Field(ge=0.0, le=1.0)
    probability_pct: float = 0.0
    engine: str
    symbol: Optional[str] = None
    high_confidence: Optional[float] = Field(default=None, ge=0.85, le=1.0)


class MarketOutlookScenario(BaseModel):
    scenario: str
    label_ru: str
    probability: float = Field(ge=0.0, le=1.0)
    probability_pct: float = 0.0
    engine: str
    high_confidence: Optional[float] = Field(default=None, ge=0.85, le=1.0)


class RegimeForecastOut(BaseModel):
    dominant_regime: str
    dominant_regime_ru: str
    confidence: float
    distribution: list[ForecastPredictionItem] = Field(default_factory=list)
    engine: str = "RegimeEngine"


class StructuredForecastSections(BaseModel):
    market_outlook: list[MarketOutlookScenario] = Field(default_factory=list)
    sector_opportunities: list[ForecastPredictionItem] = Field(default_factory=list)
    sector_risks: list[ForecastPredictionItem] = Field(default_factory=list)
    regime_forecast: RegimeForecastOut | dict[str, Any] = Field(default_factory=dict)
    tail_risk_events: list[ForecastPredictionItem] = Field(default_factory=list)
    actionable_summary: list[str] = Field(default_factory=list)
    high_confidence_predictions: list[ForecastPredictionItem] = Field(default_factory=list)
    engines_used: list[str] = Field(default_factory=list)


class ScenarioDisclosureOut(BaseModel):
    paragraphs: list[str] = Field(default_factory=list)
    top_scenario: str = ""
    top_probability: float = 0.0
    second_scenario: str | None = None
    second_probability: float | None = None
    scenarios: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    engines_used: list[str] = Field(default_factory=list)
    scope: str = "market"
    layers: dict[str, Any] = Field(default_factory=dict)
    breakdown: dict[str, float] = Field(default_factory=dict)
    freshness: dict[str, Any] = Field(default_factory=dict)
    expected_move: float = 0.0
    volatility_regime: str = "moderate"
    risk_action: str = "wait"
    confidence: float = 0.0


class EnsembleModelOut(BaseModel):
    family: str
    family_label: str = ""
    family_label_ru: str = ""
    direction: int
    expected_return: float
    weight: float
    recent_accuracy: float
    available: bool
    note: str = ""


class BocpdForecastOut(BaseModel):
    changepoint_probability: float = 0.0
    run_length_mode: int = 0
    regime_uncertain: bool = False
    agrees_with_hmm: bool | None = None
    hmm_regime: str | None = None
    note: str = ""


class EnsembleForecastOut(BaseModel):
    median_return: float = 0.0
    direction_consensus: int = 0
    models_agreeing: int = 0
    models_total: int = 0
    insufficient_history: bool = False
    history_bars: int = 0
    direction_suppressed: bool = False
    suppression_message_ru: str | None = None
    bocpd: BocpdForecastOut | None = None
    component_models: list[EnsembleModelOut] = Field(default_factory=list)
    engine_overlays: dict[str, Any] | None = None


class ConformalIntervalOut(BaseModel):
    horizon_days: int = 30
    median_return: float = 0.0
    lower_70: float = 0.0
    upper_70: float = 0.0
    lower_90: float = 0.0
    upper_90: float = 0.0
    method: str = ""
    sufficient_data: bool = False


class BullBaseBearOut(BaseModel):
    key: str
    label_ru: str
    probability: float
    expected_return: float | None = None
    narrative: str = ""


class GlobalMacroViewOut(BaseModel):
    correlation_matrix: dict[str, dict[str, float]] = Field(default_factory=dict)
    correlation_symbols: list[str] = Field(default_factory=list)
    regime_map: list[dict[str, Any]] = Field(default_factory=list)
    factor_rotation: list[dict[str, Any]] = Field(default_factory=list)
    as_of: str = ""


class LiveDirectionAccuracyOut(BaseModel):
    accuracy: float | None = None
    sample_size: int = 0
    ci_low: float | None = None
    ci_high: float | None = None
    horizon_days: int = 10
    window_days: int = 30
    formatted_ru: str = ""


class TrackRecordChartOut(BaseModel):
    calibration_bins: list[dict[str, Any]] = Field(default_factory=list)
    rolling_accuracy: list[dict[str, Any]] = Field(default_factory=list)
    aggregate_calibration_error: float | None = None
    drift_flag: bool = False
    data_source: str = "unknown"
    disclaimer_ru: str = ""
    # Deprecated aliases for backward compatibility.
    live_vs_backtest_gap: float | None = None


class ForecastOut(BaseModel):
    symbol: str
    instrument_id: int
    dominant_regime: Optional[str] = None
    regime_distribution: dict[str, float] = Field(default_factory=dict)
    composite_risk_score: float = 0.0
    confidence: float = 0.0
    risk_flags: list[str] = Field(default_factory=list)
    factor_exposures: dict[str, float] = Field(default_factory=dict)
    probability_map: dict[str, float] = Field(default_factory=dict)
    metric_validity: dict[str, bool] = Field(
        default_factory=dict,
        description="Per-metric is_valid flags; false means show недостаточно данных",
    )
    data_quality: dict[str, str] = Field(
        default_factory=dict,
        description="Reason codes for invalid metrics (e.g. insufficient_data)",
    )
    forecast_explanation: Optional[str] = None
    regime_explanation: Optional[str] = None
    risk_explanation: Optional[str] = None
    risk_engine_metrics: dict[str, Any] = Field(default_factory=dict)
    source_metrics: dict[str, Any] = Field(default_factory=dict)
    structured: StructuredForecastSections | None = None
    hierarchy_output: dict[str, Any] | None = Field(
        default=None,
        description="6-layer ForecastOutput from PredictionHierarchyOrchestrator",
    )
    action_recommendation: Optional[str] = None
    narrator_insights: list[str] = Field(default_factory=list)
    scenario_disclosure: ScenarioDisclosureOut | None = None
    llm_narrative: str | None = Field(
        default=None,
        description="Optional Kimi narrative when LLM_ENABLED; does not alter model numbers",
    )
    as_of: Optional[datetime] = None
    snapshot_id: Optional[str] = None
    ticker_analysis: TickerAnalysisPayload | None = None
    ensemble_forecast: EnsembleForecastOut | None = None
    conformal_intervals: ConformalIntervalOut | None = None
    bull_base_bear: list[BullBaseBearOut] = Field(default_factory=list)
    global_macro: GlobalMacroViewOut | None = None
    track_record_chart: TrackRecordChartOut | None = None
    live_direction_accuracy: LiveDirectionAccuracyOut | None = None
    market_beat: dict[str, Any] | None = None


class DailyForecastItem(BaseModel):
    symbol: str
    instrument_id: int
    as_of: datetime
    snapshot_id: str
    payload: StructuredForecastSections
    composite_risk_score: float = 0.0
    confidence: float = 0.0


class DailyForecastOut(BaseModel):
    items: list[DailyForecastItem] = Field(default_factory=list)
    count: int = 0


class MarketOutlookPointOut(BaseModel):
    title: str
    what_happens: str
    how: str
    where: str
    expectations: str
    prognosis: str
    evidence_basis: list[str] = Field(default_factory=list)
    confidence_pct: float = 0.0


class MarketPredictionSummaryOut(BaseModel):
    paragraphs: list[str] = Field(default_factory=list)
    coverage: list[str] = Field(default_factory=list)
    engines_used: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    missing_resources: list[str] = Field(default_factory=list)
    confidence_pct: float = 0.0


class MarketForecastOut(BaseModel):
    as_of: datetime
    global_regime: dict[str, Any] = Field(default_factory=dict)
    market_outlook: list[MarketOutlookPointOut] = Field(default_factory=list)
    sector_rotation: list[dict[str, Any]] = Field(default_factory=list)
    calibrated_probabilities: dict[str, float] = Field(default_factory=dict)
    macro_indicators: dict[str, float] = Field(default_factory=dict)
    macro_block: dict[str, Any] | None = Field(
        default=None,
        description="Macro Registry block: indicators, upcoming releases, missing resources",
    )
    market_prediction_summary: MarketPredictionSummaryOut | None = None
    scenario_disclosure: ScenarioDisclosureOut | None = None
    llm_narrative: str | None = Field(
        default=None,
        description="Optional Kimi narrative when LLM_ENABLED",
    )


class ForecastNarrativeOut(BaseModel):
    """LLM narrative enrichment for a symbol — call after core /forecast load."""

    symbol: str
    llm_narrative: str | None = None
    scenario_disclosure: ScenarioDisclosureOut | None = None
    actionable_summary: list[str] = Field(default_factory=list)


class ForecastHealthOut(BaseModel):
    status: str = "ok"
    symbol: str
    instrument_id: int
    hierarchy_output: dict[str, Any]
    checks: dict[str, str] = Field(default_factory=dict)
    sli: dict[str, Any] = Field(default_factory=dict)
