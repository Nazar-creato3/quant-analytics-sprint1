"""Shared risk module for all bot types (Grid, DCA, Momentum, ...)."""
from app.services.bot_risk.guard import (
    BotRiskGuard,
    build_snapshot_from_stores,
    get_bot_risk_guard,
    run_portfolio_circuit_breaker,
)
from app.services.bot_risk.types import (
    BotRef,
    CircuitBreakerResult,
    CorrelationCheckResult,
    PortfolioSnapshot,
    PositionSizeResult,
)

__all__ = [
    "BotRef",
    "BotRiskGuard",
    "CircuitBreakerResult",
    "CorrelationCheckResult",
    "PortfolioSnapshot",
    "PositionSizeResult",
    "build_snapshot_from_stores",
    "get_bot_risk_guard",
    "run_portfolio_circuit_breaker",
]
