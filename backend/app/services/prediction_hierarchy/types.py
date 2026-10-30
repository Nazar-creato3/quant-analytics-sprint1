"""Typed domain models for the prediction hierarchy (Prompts 31-40)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.services.regime.types import RegimeClassificationResult


class GlobalRegimeLabel(StrEnum):
    """Macro aggregate regime labels (Prompt 32)."""

    RISK_ON = "risk_on"
    RISK_OFF = "risk_off"
    MACRO_UNCERTAINTY = "macro_uncertainty"
    CREDIT_STRESS = "credit_stress"
    INFLATION_SHOCK_REGIME = "inflation_shock_regime"


class SectorRotationFlag(StrEnum):
    """Sector rotation classification (Prompt 31)."""

    SECTORS_STRENGTHENING = "sectors_strengthening"
    SECTORS_WEAKENING = "sectors_weakening"
    ROTATION_IN_PROGRESS = "rotation_in_progress"
    NEUTRAL = "neutral"


class PointMagnitudeClass(StrEnum):
    """Expected return sign + magnitude (not price)."""

    STRONG_UP = "strong_up"
    UP = "up"
    NEUTRAL = "neutral"
    DOWN = "down"
    STRONG_DOWN = "strong_down"


class ActionRecommendation(StrEnum):
    """Rule-based action forecast (Prompt 35) — advisory only."""

    WAIT = "wait"
    REDUCE_SIZE = "reduce_size"
    HEDGE = "hedge"
    HOLD = "hold"
    ENTER_SMALL_SIZE = "enter_small_size"
    ENTER_NORMAL_SIZE = "enter_normal_size"
    AVOID = "avoid"


HIGH_CONFIDENCE_THRESHOLD = 0.85


@dataclass(frozen=True, slots=True)
class SectorRotationScore:
    """Relative sector strength across horizons (Prompt 31)."""

    sector: str
    score_1w: float
    score_1m: float
    score_3m: float
    composite_score: float
    rotation_flag: SectorRotationFlag
    rank: int = 0


@dataclass(frozen=True, slots=True)
class SectorRegimeContext:
    """Sector-level regime + rotation context."""

    sector: str
    regime: RegimeClassificationResult
    rotation: SectorRotationScore
    sector_momentum: float


@dataclass(frozen=True, slots=True)
class GlobalRegimeResult:
    """Probabilistic global macro regime (Prompt 32)."""

    distribution: dict[str, float]
    dominant_regime: str
    confidence: float
    confirmation_window_bars: int
    confidence_damping_active: bool
    credit_spread_proxy: float | None = None
    credit_spread_source: str = "unavailable"

    def validate(self) -> None:
        total = sum(self.distribution.values())
        if not (0.999 <= total <= 1.001):
            raise ValueError(f"distribution must sum to 1.0, got {total}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class PointForecast:
    magnitude_class: PointMagnitudeClass
    expected_return_sign: int
    momentum_score: float
    plain_language_summary: str = ""


@dataclass(frozen=True, slots=True)
class IntervalForecast:
    horizon_days: int
    p10: float
    p90: float
    rolling_volatility: float
    confidence_multiplier: float
    plain_language_summary: str = ""


@dataclass(frozen=True, slots=True)
class DistributionForecast:
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float
    method: str
    plain_language_summary: str = ""


@dataclass(frozen=True, slots=True)
class ScenarioForecastItem:
    name: str
    probability: float
    impact: float
    label_ru: str = ""
    scenario_type: str = ""
    impact_narrative_ru: str = ""


@dataclass(frozen=True, slots=True)
class ScenarioForecast:
    scenarios: tuple[ScenarioForecastItem, ...]
    scenario_dispersion: float
    overlay_breakdown: dict[str, float] = field(default_factory=dict)
    overlay_audit: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BasisLayerBlock:
    """Per-layer explainability for non-traders."""

    layer: str
    engine: str
    input_metrics: dict[str, float]
    conclusion_ru: str


@dataclass(frozen=True, slots=True)
class MarketOutlookPoint:
    """Detailed market-wide outlook bullet."""

    title: str
    what_happens: str
    how: str
    where: str
    expectations: str
    prognosis: str
    evidence_basis: tuple[str, ...]
    confidence_pct: float


@dataclass(frozen=True, slots=True)
class MarginalRiskImpact:
    delta_var: float
    delta_es: float
    component_contributions: dict[int, float]
    new_concentration_risk: float
    new_correlation_cluster_exposure: float


@dataclass(frozen=True, slots=True)
class RiskItem:
    """Deduplicated risk flag with plain-language explanation."""

    metric: str
    score: float
    severity: str
    plain_language_summary: str


@dataclass(frozen=True, slots=True)
class RiskForecastLayer:
    instrument_metrics: dict[str, float]
    portfolio_metrics: dict[str, float]
    marginal_impact: MarginalRiskImpact | None = None
    breached_metrics: tuple[str, ...] = ()
    plain_language_summary: str = ""
    risk_items: tuple[RiskItem, ...] = ()


@dataclass(frozen=True, slots=True)
class ActionForecast:
    recommendation: ActionRecommendation
    reason: str
    rule_id: str


@dataclass(frozen=True, slots=True)
class NarratorInsight:
    template_id: str
    text_ru: str
    text_en: str
    source_metric: str
    source_value: float


@dataclass(frozen=True, slots=True)
class ForecastOutput:
    """Unified 6-layer forecast output (Prompt 34)."""

    instrument_id: int
    symbol: str
    as_of: str
    point_forecast: PointForecast
    interval_forecast: IntervalForecast
    distribution_forecast: DistributionForecast
    scenario_forecast: ScenarioForecast
    risk_forecast: RiskForecastLayer
    action_forecast: ActionForecast
    calibrated_confidence: float
    high_confidence: bool
    global_regime: GlobalRegimeResult | None = None
    sector_regime: SectorRegimeContext | None = None
    narrator_insights: tuple[NarratorInsight, ...] = ()
    raw_ticker_confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    instruction_block: str = ""
    basis_block: tuple[BasisLayerBlock, ...] = ()
    risk_engine_report: dict[str, Any] = field(default_factory=dict)
    prediction_system_report: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "as_of": self.as_of,
            "instruction_block": self.instruction_block,
            "basis_block": [
                {
                    "layer": block.layer,
                    "engine": block.engine,
                    "input_metrics": block.input_metrics,
                    "conclusion_ru": block.conclusion_ru,
                }
                for block in self.basis_block
            ],
            "point_forecast": {
                "magnitude_class": self.point_forecast.magnitude_class.value,
                "expected_return_sign": self.point_forecast.expected_return_sign,
                "momentum_score": self.point_forecast.momentum_score,
                "plain_language_summary": self.point_forecast.plain_language_summary,
            },
            "interval_forecast": {
                "horizon_days": self.interval_forecast.horizon_days,
                "p10": self.interval_forecast.p10,
                "p90": self.interval_forecast.p90,
                "rolling_volatility": self.interval_forecast.rolling_volatility,
                "plain_language_summary": self.interval_forecast.plain_language_summary,
            },
            "distribution_forecast": {
                "p5": self.distribution_forecast.p5,
                "p25": self.distribution_forecast.p25,
                "p50": self.distribution_forecast.p50,
                "p75": self.distribution_forecast.p75,
                "p95": self.distribution_forecast.p95,
                "method": self.distribution_forecast.method,
                "plain_language_summary": self.distribution_forecast.plain_language_summary,
            },
            "scenario_forecast": {
                "scenarios": [
                    {
                        "name": s.name,
                        "scenario_type": s.scenario_type,
                        "label_ru": s.label_ru,
                        "probability": s.probability,
                        "impact": s.impact,
                        "impact_narrative_ru": s.impact_narrative_ru,
                    }
                    for s in self.scenario_forecast.scenarios
                ],
                "scenario_dispersion": self.scenario_forecast.scenario_dispersion,
                "overlay_breakdown": dict(self.scenario_forecast.overlay_breakdown),
                "overlay_audit": dict(self.scenario_forecast.overlay_audit),
            },
            "risk_forecast": {
                "instrument_metrics": self.risk_forecast.instrument_metrics,
                "portfolio_metrics": self.risk_forecast.portfolio_metrics,
                "breached_metrics": list(self.risk_forecast.breached_metrics),
                "plain_language_summary": self.risk_forecast.plain_language_summary,
                "risk_items": [
                    {
                        "metric": item.metric,
                        "score": item.score,
                        "severity": item.severity,
                        "plain_language_summary": item.plain_language_summary,
                    }
                    for item in self.risk_forecast.risk_items
                ],
                "marginal_impact": (
                    {
                        "delta_var": self.risk_forecast.marginal_impact.delta_var,
                        "delta_es": self.risk_forecast.marginal_impact.delta_es,
                    }
                    if self.risk_forecast.marginal_impact
                    else None
                ),
            },
            "action_forecast": {
                "recommendation": self.action_forecast.recommendation.value,
                "reason": self.action_forecast.reason,
                "rule_id": self.action_forecast.rule_id,
            },
            "calibrated_confidence": self.calibrated_confidence,
            "high_confidence": self.high_confidence,
            "global_regime": (
                {
                    "dominant_regime": self.global_regime.dominant_regime,
                    "confidence": self.global_regime.confidence,
                    "distribution": self.global_regime.distribution,
                }
                if self.global_regime
                else None
            ),
            "sector_regime": (
                {
                    "sector": self.sector_regime.sector,
                    "regime": {
                        "dominant_regime": self.sector_regime.regime.dominant_regime,
                        "distribution": self.sector_regime.regime.distribution,
                    },
                    "rotation": {
                        "rotation_flag": self.sector_regime.rotation.rotation_flag.value,
                        "composite_score": self.sector_regime.rotation.composite_score,
                        "score_1w": self.sector_regime.rotation.score_1w,
                        "score_1m": self.sector_regime.rotation.score_1m,
                        "score_3m": self.sector_regime.rotation.score_3m,
                    },
                    "sector_momentum": self.sector_regime.sector_momentum,
                }
                if self.sector_regime
                else None
            ),
            "narrator_insights": [
                {
                    "template_id": i.template_id,
                    "text_ru": i.text_ru,
                    "text_en": i.text_en,
                    "source_metric": i.source_metric,
                    "source_value": i.source_value,
                }
                for i in self.narrator_insights
            ],
            "risk_engine_report": self.risk_engine_report,
            "prediction_system_report": self.prediction_system_report,
            "metadata": self.metadata,
        }


@dataclass(frozen=True, slots=True)
class PortfolioContext:
    """Optional portfolio for marginal risk (Prompt 33)."""

    positions: tuple[Any, ...]
    returns_by_instrument: dict[int, list[float]]
    sector_by_instrument: dict[int, str] | None = None
    remaining_risk_budget_var: float | None = None
    correlation_edges: tuple[Any, ...] = ()
    factor_exposures: dict[int, dict[str, float]] | None = None


@dataclass(frozen=True, slots=True)
class ProposedPositionChange:
    """Hypothetical position change for what_if()."""

    instrument_id: int
    sleeve_id: str = "default"
    delta_weight: float = 0.0
    new_weight: float | None = None
