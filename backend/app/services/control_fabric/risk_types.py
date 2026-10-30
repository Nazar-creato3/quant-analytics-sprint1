"""RiskEngine domain types — metric assessments for Prompt 23."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from app.domain.enums import AssetCategory
from app.services.factor.types import FactorName
from app.services.market_graph.types import GraphEdgeRow
from app.services.scenario.types import PortfolioPosition


RiskScope = Literal["instrument", "portfolio"]


@dataclass(frozen=True, slots=True)
class RiskMetricAssessment:
    """Single risk metric with explicit threshold comparison."""

    name: str
    value: float
    threshold: float
    exceeded: bool
    scope: RiskScope
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InstrumentRiskAssessment:
    """Per-instrument risk metrics."""

    instrument_id: int
    metrics: tuple[RiskMetricAssessment, ...]

    @property
    def breached(self) -> tuple[RiskMetricAssessment, ...]:
        return tuple(metric for metric in self.metrics if metric.exceeded)


@dataclass(frozen=True, slots=True)
class PortfolioRiskAssessment:
    """Portfolio-level risk metrics plus per-instrument breakdown."""

    metrics: tuple[RiskMetricAssessment, ...]
    instrument_assessments: tuple[InstrumentRiskAssessment, ...] = ()

    @property
    def breached(self) -> tuple[RiskMetricAssessment, ...]:
        instrument_breaches = [
            metric
            for assessment in self.instrument_assessments
            for metric in assessment.metrics
            if metric.exceeded
        ]
        portfolio_breaches = [metric for metric in self.metrics if metric.exceeded]
        return tuple(portfolio_breaches + instrument_breaches)

    def to_dict(self) -> dict[str, Any]:
        return {
            "portfolio_metrics": [
                {
                    "name": metric.name,
                    "value": metric.value,
                    "threshold": metric.threshold,
                    "exceeded": metric.exceeded,
                    "scope": metric.scope,
                    "metadata": metric.metadata,
                }
                for metric in self.metrics
            ],
            "instrument_metrics": {
                str(assessment.instrument_id): [
                    {
                        "name": metric.name,
                        "value": metric.value,
                        "threshold": metric.threshold,
                        "exceeded": metric.exceeded,
                        "scope": metric.scope,
                    }
                    for metric in assessment.metrics
                ]
                for assessment in self.instrument_assessments
            },
            "breached_count": len(self.breached),
        }


@dataclass(frozen=True, slots=True)
class RiskEngineInput:
    """Inputs for RiskEngine assessment (pure or from live context)."""

    instrument_id: int
    returns_by_instrument: dict[int, list[float]]
    positions: tuple[PortfolioPosition, ...] = ()
    factor_exposures: dict[int, dict[FactorName, float]] = field(default_factory=dict)
    sector_by_instrument: dict[int, str] = field(default_factory=dict)
    prices_by_instrument: dict[int, list[float]] = field(default_factory=dict)
    overnight_returns_by_instrument: dict[int, list[float]] = field(default_factory=dict)
    correlation_edges: tuple[GraphEdgeRow, ...] | None = None
    tail_risk_score: float | None = None
    liquidity_risk_score: float | None = None
    event_risk_active: bool = False
    active_lock_instrument_ids: frozenset[int] = frozenset()
    asset_category: AssetCategory | None = None
    proposed_weight: float = 0.0
    portfolio_value_usd: float = 1.0
    correlation_threshold: float = 0.7


@dataclass(frozen=True, slots=True)
class RiskBudgetContext:
    """Threshold source from profile and sleeve."""

    diversification_policy: dict[str, Any]
    max_drawdown_pct: float
    sleeve_risk_budget: Decimal
    profile_max_daily_loss: Decimal
