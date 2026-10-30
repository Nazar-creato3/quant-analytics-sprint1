"""Pydantic I/O models for Terminal Quant/Risk modules."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class Asset(BaseModel):
    """Single tradable asset identifier."""

    symbol: str = Field(..., min_length=1)
    name: str | None = None
    asset_class: str | None = None


class OHLCVBar(BaseModel):
    """Normalized OHLCV bar (connector output)."""

    timestamp: str | None = None
    open: float
    high: float
    low: float
    close: float = Field(..., gt=0.0)
    volume: float | None = None


class ReturnSeries(BaseModel):
    """Period returns (simple or log — caller-defined convention)."""

    symbol: str = "PORTFOLIO"
    values: list[float] = Field(..., min_length=1)
    periods_per_year: int = Field(default=252, gt=0)
    risk_free_rate: float = Field(default=0.0, description="Annual risk-free rate")

    @field_validator("values")
    @classmethod
    def _finite(cls, values: list[float]) -> list[float]:
        for value in values:
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError("returns must be finite")
        return values


class PriceSeries(BaseModel):
    """Price levels for CAGR / drawdown."""

    symbol: str = "PORTFOLIO"
    values: list[float] = Field(..., min_length=2)
    periods_per_year: int = Field(default=252, gt=0)

    @field_validator("values")
    @classmethod
    def _positive_finite(cls, values: list[float]) -> list[float]:
        for value in values:
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError("prices must be finite")
            if value <= 0.0:
                raise ValueError("prices must be strictly positive")
        return values


class PortfolioPositionWeights(BaseModel):
    """Weight allocation for one asset."""

    symbol: str = Field(..., min_length=1)
    weight: float


class Portfolio(BaseModel):
    """Portfolio composition (weights should sum ~1)."""

    name: str = "portfolio"
    positions: list[PortfolioPositionWeights] = Field(..., min_length=1)
    value_usd: float = Field(default=1.0, gt=0.0)

    @model_validator(mode="after")
    def _validate_weights(self) -> Portfolio:
        total = sum(abs(p.weight) for p in self.positions)
        if total <= 0.0:
            raise ValueError("portfolio weights must not be all zero")
        return self

    def weight_vector(self, symbols: list[str]) -> list[float]:
        lookup = {p.symbol: p.weight for p in self.positions}
        return [float(lookup.get(symbol, 0.0)) for symbol in symbols]


class ExpectedReturns(BaseModel):
    """Expected return vector aligned to symbols."""

    symbols: list[str] = Field(..., min_length=1)
    values: list[float] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _align(self) -> ExpectedReturns:
        if len(self.symbols) != len(self.values):
            raise ValueError("symbols and values length mismatch")
        return self


class CovMatrix(BaseModel):
    """Covariance matrix aligned to symbols."""

    symbols: list[str] = Field(..., min_length=1)
    matrix: list[list[float]] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _square(self) -> CovMatrix:
        n = len(self.symbols)
        if len(self.matrix) != n:
            raise ValueError("covariance row count must match symbols")
        for row in self.matrix:
            if len(row) != n:
                raise ValueError("covariance matrix must be square")
        return self


class RiskMetrics(BaseModel):
    """Bundle of core risk/return analytics."""

    sharpe: float
    sortino: float
    cagr: float | None = None
    volatility: float
    volatility_annual: float
    max_drawdown: float
    beta: float | None = None
    correlation: float | None = None
    periods_per_year: int = 252
    n_observations: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class VaRMethodName(str, Enum):
    HISTORICAL = "historical"
    PARAMETRIC = "parametric"
    MONTE_CARLO = "monte_carlo"


class VaRResult(BaseModel):
    """Value-at-Risk as a positive loss fraction (of notional)."""

    method: VaRMethodName
    confidence: float = Field(..., gt=0.0, lt=1.0)
    var: float
    cvar: float | None = None
    horizon_periods: int = 1
    n_simulations: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OptimizedPortfolio(BaseModel):
    """Mean-variance optimization result."""

    symbols: list[str]
    weights: list[float]
    expected_return: float
    volatility: float
    sharpe: float
    objective: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class FrontierPoint(BaseModel):
    """One point on the efficient frontier."""

    target_return: float
    volatility: float
    sharpe: float
    weights: list[float]


class EfficientFrontierResult(BaseModel):
    """Efficient frontier curve plus max-Sharpe / min-variance anchors."""

    symbols: list[str]
    points: list[FrontierPoint]
    max_sharpe: OptimizedPortfolio
    min_variance: OptimizedPortfolio


class StressScenario(BaseModel):
    """Named stress scenario applied to portfolio weights × asset shocks."""

    name: str
    description: str | None = None
    asset_shocks: dict[str, float] = Field(
        ...,
        description="Symbol → return shock (e.g. -0.20 for -20%)",
    )


class ShockSpec(BaseModel):
    """Arbitrary shock vector for ad-hoc analysis."""

    shocks: dict[str, float] = Field(..., min_length=1)
    label: str = "custom"


class StressResult(BaseModel):
    """Stressed P&L impact."""

    scenario_name: str
    portfolio_pnl_pct: float
    portfolio_pnl_usd: float
    contribution_by_symbol: dict[str, float]
    metadata: dict[str, Any] = Field(default_factory=dict)


class SignalSide(str, Enum):
    FLAT = "flat"
    LONG = "long"
    SHORT = "short"


class BacktestConfig(BaseModel):
    """Backtest / walk-forward configuration."""

    initial_capital: float = Field(default=100_000.0, gt=0.0)
    signal_lookback: int = Field(default=20, ge=1)
    transaction_cost_bps: float = Field(default=0.0, ge=0.0)
    allow_short: bool = False
    periods_per_year: int = Field(default=252, gt=0)
    risk_free_rate: float = 0.0


class BacktestResult(BaseModel):
    """Single-window backtest output."""

    equity_curve: list[float]
    returns: list[float]
    signals: list[int] = Field(description="Position: -1, 0, +1 per bar")
    total_return: float
    cagr: float
    sharpe: float
    sortino: float
    max_drawdown: float
    volatility_annual: float
    win_rate: float
    n_trades: int
    metrics: RiskMetrics
    metadata: dict[str, Any] = Field(default_factory=dict)


class WalkForwardFold(BaseModel):
    """One train/test fold."""

    fold_index: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    test_result: BacktestResult


class WalkForwardResult(BaseModel):
    """Walk-forward aggregation."""

    folds: list[WalkForwardFold]
    aggregate: BacktestResult
    mean_test_sharpe: float
    mean_test_max_drawdown: float


class QuantRiskLimits(BaseModel):
    """Limits for terminal quant pre/post trade checks."""

    max_position_weight: float = Field(default=0.25, gt=0.0)
    max_portfolio_var: float = Field(default=0.05, gt=0.0)
    max_drawdown: float = Field(default=0.20, gt=0.0)
    max_daily_loss: float = Field(default=0.05, gt=0.0)
    var_confidence: float = Field(default=0.95, gt=0.5, lt=1.0)
    enforce: bool = Field(
        default=False,
        description="When False, checks annotate only (never block production).",
    )


class QuantRiskDecision(BaseModel):
    """Pre/post trade decision from terminal quant risk manager."""

    approved: bool
    stage: str
    reason: str
    var: float | None = None
    drawdown: float | None = None
    metrics: RiskMetrics | None = None
    explanation: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class MetricsRequest(BaseModel):
    returns: ReturnSeries
    prices: PriceSeries | None = None
    benchmark_returns: ReturnSeries | None = None


class VaRRequest(BaseModel):
    returns: ReturnSeries
    confidence: float = Field(default=0.95, gt=0.5, lt=1.0)
    method: VaRMethodName = VaRMethodName.HISTORICAL
    n_simulations: int = Field(default=10_000, ge=100, le=200_000)
    seed: int | None = 42


class PortfolioOptRequest(BaseModel):
    expected_returns: ExpectedReturns
    cov_matrix: CovMatrix
    risk_free_rate: float = 0.0
    long_only: bool = True
    n_frontier_points: int = Field(default=25, ge=3, le=200)


class StressRequest(BaseModel):
    portfolio: Portfolio
    scenario: StressScenario | None = None
    shocks: ShockSpec | None = None

    @model_validator(mode="after")
    def _one_shock_source(self) -> StressRequest:
        if self.scenario is None and self.shocks is None:
            raise ValueError("provide scenario or shocks")
        return self


class BacktestRequest(BaseModel):
    prices: PriceSeries
    config: BacktestConfig = Field(default_factory=BacktestConfig)


class WalkForwardRequest(BaseModel):
    prices: PriceSeries
    train_window: int = Field(..., ge=10)
    test_window: int = Field(..., ge=5)
    config: BacktestConfig = Field(default_factory=BacktestConfig)


class PreTradeRequest(BaseModel):
    proposed_weight: float = Field(..., ge=0.0)
    symbol: str
    portfolio: Portfolio
    historical_returns: ReturnSeries
    prices: PriceSeries | None = None
    limits: QuantRiskLimits = Field(default_factory=QuantRiskLimits)


class PostTradeRequest(BaseModel):
    portfolio: Portfolio
    historical_returns: ReturnSeries
    prices: PriceSeries
    limits: QuantRiskLimits = Field(default_factory=QuantRiskLimits)


class ExplainRequest(BaseModel):
    metrics: RiskMetrics | None = None
    var_result: VaRResult | None = None
    decision: QuantRiskDecision | None = None
