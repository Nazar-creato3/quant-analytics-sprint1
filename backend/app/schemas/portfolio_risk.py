"""API schemas for portfolio risk analytics."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RiskHoldingOut(BaseModel):
    symbol: str
    notional_usd: float
    weight: float
    sector: str = "unknown"


class StressScenarioMetaOut(BaseModel):
    id: str
    label_ru: str
    start: str
    end: str
    description_ru: str


class StressCurvePointOut(BaseModel):
    date: str
    equity: float


class StressResultOut(BaseModel):
    scenario_id: str
    label_ru: str
    start: str
    end: str
    description_ru: str
    total_return: float | None = None
    max_drawdown: float | None = None
    worst_day_return: float | None = None
    missing_symbols: list[str] = Field(default_factory=list)
    observations: int = 0
    equity_curve: list[StressCurvePointOut] = Field(default_factory=list)
    methodology_ru: str = ""


class PortfolioRiskAnalyticsOut(BaseModel):
    computed_at: str
    lookback_start: str = ""
    lookback_end: str = ""
    lookback_days: int
    data_as_of: str
    nav_usd: float
    holdings: list[RiskHoldingOut] = Field(default_factory=list)
    sector_weights: dict[str, float] = Field(default_factory=dict)
    var_95: float | None = None
    var_99: float | None = None
    expected_shortfall_95: float | None = None
    var_95_usd: float | None = None
    var_99_usd: float | None = None
    expected_shortfall_95_usd: float | None = None
    observations: int = 0
    alpha: float | None = None
    beta: float | None = None
    r_squared: float | None = None
    alpha_daily: float | None = None
    benchmark_symbol: str = "SPY"
    market_driven_return: float | None = None
    residual_return: float | None = None
    portfolio_window_return: float | None = None
    correlation_symbols: list[str] = Field(default_factory=list)
    correlation_matrix: list[list[float | None]] = Field(default_factory=list)
    avg_pairwise_correlation: float | None = None
    concentration_share: float | None = None
    concentration_flag_ru: str | None = None
    factor_exposures: dict[str, float] = Field(default_factory=dict)
    stress: list[StressResultOut] = Field(default_factory=list)
    insufficient_data: bool = False
    methodology: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
