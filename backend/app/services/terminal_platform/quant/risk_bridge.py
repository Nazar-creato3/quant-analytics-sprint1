"""Soft integration hooks for Control Fabric RiskGate (opt-in, non-breaking)."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.services.terminal_platform.quant.models import (
    Portfolio,
    PortfolioPositionWeights,
    PriceSeries,
    QuantRiskDecision,
    QuantRiskLimits,
    ReturnSeries,
)
from app.services.terminal_platform.quant.risk_manager import post_trade_check, pre_trade_check


def enrich_risk_gate_metadata(
    metadata: dict[str, Any],
    *,
    symbol: str,
    proposed_weight: float,
    historical_returns: Sequence[float] | None,
    equity_curve: Sequence[float] | None = None,
    positions: Mapping[str, float] | None = None,
    limits: QuantRiskLimits | None = None,
) -> dict[str, Any]:
    """Attach terminal quant pre-trade diagnostics to RiskGate metadata.

    Never raises into the production gate path — failures become metadata notes.
    Does not change allow/block unless caller separately reads ``enforce``.
    """
    out = dict(metadata)
    if historical_returns is None or len(historical_returns) == 0:
        out["terminal_quant"] = {"skipped": True, "reason": "no historical_returns"}
        return out

    try:
        portfolio = _portfolio_from_positions(positions)
        prices = (
            PriceSeries(symbol=symbol, values=list(equity_curve))
            if equity_curve is not None and len(equity_curve) >= 2
            else None
        )
        decision = pre_trade_check(
            order_symbol=symbol,
            proposed_weight=proposed_weight,
            portfolio=portfolio,
            historical_returns=ReturnSeries(symbol=symbol, values=list(historical_returns)),
            limits=limits or QuantRiskLimits(enforce=False),
            prices=prices,
        )
        out["terminal_quant"] = decision.model_dump()
    except Exception as exc:  # noqa: BLE001 — never break RiskGate
        out["terminal_quant"] = {"error": str(exc), "skipped": True}
    return out


def run_post_trade_hook(
    *,
    symbol: str,
    historical_returns: Sequence[float],
    equity_curve: Sequence[float],
    positions: Mapping[str, float] | None = None,
    limits: QuantRiskLimits | None = None,
) -> QuantRiskDecision:
    """Post-trade refresh used by callers after fill confirmation."""
    return post_trade_check(
        portfolio=_portfolio_from_positions(positions),
        historical_returns=ReturnSeries(symbol=symbol, values=list(historical_returns)),
        prices=PriceSeries(symbol=symbol, values=list(equity_curve)),
        limits=limits or QuantRiskLimits(enforce=False),
    )


def _portfolio_from_positions(positions: Mapping[str, float] | None) -> Portfolio:
    if not positions:
        return Portfolio(
            name="default",
            positions=[PortfolioPositionWeights(symbol="CASH", weight=1.0)],
        )
    return Portfolio(
        name="live",
        positions=[
            PortfolioPositionWeights(symbol=str(sym), weight=float(w))
            for sym, w in positions.items()
        ],
    )
