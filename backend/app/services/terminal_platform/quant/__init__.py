"""Terminal Quant/Risk package — reusable analytics for the own-terminal stack.

Wraps ``app.services.quant_math`` where applicable and exposes Pydantic I/O
for metrics, VaR, portfolio optimization, stress, and backtests.
"""
from __future__ import annotations

from app.services.terminal_platform.quant.backtest import (
    analyze_backtest,
    run_backtest,
    walk_forward,
)
from app.services.terminal_platform.quant.explainer import RiskExplainer
from app.services.terminal_platform.quant.metrics import (
    beta,
    cagr,
    compute_risk_metrics,
    correlation_pair,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
    volatility,
)
from app.services.terminal_platform.quant.models import (
    Asset,
    BacktestConfig,
    BacktestResult,
    CovMatrix,
    EfficientFrontierResult,
    ExpectedReturns,
    OHLCVBar,
    OptimizedPortfolio,
    Portfolio,
    PortfolioPositionWeights,
    PriceSeries,
    QuantRiskDecision,
    QuantRiskLimits,
    ReturnSeries,
    RiskMetrics,
    ShockSpec,
    StressResult,
    StressScenario,
    VaRResult,
    WalkForwardResult,
)
from app.services.terminal_platform.quant.portfolio import (
    efficient_frontier,
    optimize_min_variance,
    optimize_sharpe,
)
from app.services.terminal_platform.quant.risk_manager import (
    compute_portfolio_var,
    evaluate_risk,
    post_trade_check,
    pre_trade_check,
)
from app.services.terminal_platform.quant.stress import shock_analysis, stress_scenario
from app.services.terminal_platform.quant.var import (
    historical_var,
    monte_carlo_var,
    parametric_var,
)

__all__ = [
    "Asset",
    "BacktestConfig",
    "BacktestResult",
    "CovMatrix",
    "EfficientFrontierResult",
    "ExpectedReturns",
    "OHLCVBar",
    "OptimizedPortfolio",
    "Portfolio",
    "PortfolioPositionWeights",
    "PriceSeries",
    "QuantRiskDecision",
    "QuantRiskLimits",
    "ReturnSeries",
    "RiskExplainer",
    "RiskMetrics",
    "ShockSpec",
    "StressResult",
    "StressScenario",
    "VaRResult",
    "WalkForwardResult",
    "analyze_backtest",
    "beta",
    "cagr",
    "compute_portfolio_var",
    "compute_risk_metrics",
    "correlation_pair",
    "efficient_frontier",
    "evaluate_risk",
    "historical_var",
    "max_drawdown",
    "monte_carlo_var",
    "optimize_min_variance",
    "optimize_sharpe",
    "parametric_var",
    "post_trade_check",
    "pre_trade_check",
    "run_backtest",
    "sharpe_ratio",
    "shock_analysis",
    "sortino_ratio",
    "stress_scenario",
    "volatility",
    "walk_forward",
]
