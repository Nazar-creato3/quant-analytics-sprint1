"""Terminal Quant risk manager — pre/post trade checks (non-breaking by default).

Production RiskGate / grid_bot RiskManager remain authoritative. These helpers
annotate VaR/drawdown and only block when ``limits.enforce=True``.
"""
from __future__ import annotations

from typing import Any

from app.services.terminal_platform.quant.explainer import RiskExplainer
from app.services.terminal_platform.quant.metrics import compute_risk_metrics, max_drawdown
from app.services.terminal_platform.quant.models import (
    Portfolio,
    PortfolioPositionWeights,
    PriceSeries,
    QuantRiskDecision,
    QuantRiskLimits,
    ReturnSeries,
    VaRResult,
)
from app.services.terminal_platform.quant.var import historical_var


def compute_portfolio_var(
    portfolio: Portfolio,
    historical_returns: ReturnSeries,
    *,
    confidence: float = 0.95,
) -> VaRResult:
    """Portfolio VaR from a provided portfolio return series.

    ``portfolio`` is retained for API symmetry / future weight-aware VaR;
    callers should pass already-aggregated portfolio returns.
    """
    _ = portfolio
    return historical_var(historical_returns, confidence_level=confidence)


def pre_trade_check(
    *,
    order_symbol: str,
    proposed_weight: float,
    portfolio: Portfolio,
    historical_returns: ReturnSeries,
    limits: QuantRiskLimits | None = None,
    prices: PriceSeries | None = None,
) -> QuantRiskDecision:
    """Pre-trade gate: position size, VaR, and optional drawdown."""
    lim = limits or QuantRiskLimits()
    explainer = RiskExplainer()
    meta: dict[str, Any] = {"symbol": order_symbol, "proposed_weight": proposed_weight}

    if proposed_weight > lim.max_position_weight:
        return _decision(
            approved=False,
            stage="pre_trade",
            reason=(
                f"proposed weight {proposed_weight:.4f} exceeds "
                f"max_position_weight {lim.max_position_weight:.4f}"
            ),
            limits=lim,
            explainer=explainer,
            metadata=meta,
        )

    # Hypothetical portfolio with the proposed weight overlay (replace or add).
    hypot = _with_weight(portfolio, order_symbol, proposed_weight)
    var_result = compute_portfolio_var(
        hypot, historical_returns, confidence=lim.var_confidence
    )
    meta["var"] = var_result.var
    meta["portfolio"] = hypot.model_dump()

    if var_result.var > lim.max_portfolio_var:
        return _decision(
            approved=False,
            stage="pre_trade",
            reason=(
                f"portfolio VaR {var_result.var:.4f} exceeds "
                f"max_portfolio_var {lim.max_portfolio_var:.4f}"
            ),
            limits=lim,
            explainer=explainer,
            var=var_result.var,
            metadata=meta,
        )

    drawdown = None
    if prices is not None:
        drawdown = max_drawdown(prices)
        meta["drawdown"] = drawdown
        if drawdown > lim.max_drawdown:
            return _decision(
                approved=False,
                stage="pre_trade",
                reason=(
                    f"drawdown {drawdown:.4f} exceeds max_drawdown {lim.max_drawdown:.4f}"
                ),
                limits=lim,
                explainer=explainer,
                var=var_result.var,
                drawdown=drawdown,
                metadata=meta,
            )

    return _decision(
        approved=True,
        stage="pre_trade",
        reason="pre-trade quant checks passed",
        limits=lim,
        explainer=explainer,
        var=var_result.var,
        drawdown=drawdown,
        metadata=meta,
    )


def post_trade_check(
    *,
    portfolio: Portfolio,
    historical_returns: ReturnSeries,
    prices: PriceSeries,
    limits: QuantRiskLimits | None = None,
) -> QuantRiskDecision:
    """Post-trade: refresh metrics, flag VaR / drawdown / daily loss breaches."""
    lim = limits or QuantRiskLimits()
    explainer = RiskExplainer()
    metrics = compute_risk_metrics(historical_returns, prices=prices)
    var_result = compute_portfolio_var(
        portfolio, historical_returns, confidence=lim.var_confidence
    )
    drawdown = metrics.max_drawdown
    meta: dict[str, Any] = {
        "var": var_result.var,
        "drawdown": drawdown,
        "sharpe": metrics.sharpe,
    }

    if historical_returns.values:
        last = historical_returns.values[-1]
        if last < 0 and abs(last) > lim.max_daily_loss:
            return _decision(
                approved=False,
                stage="post_trade",
                reason=(
                    f"daily loss {abs(last):.4f} exceeds "
                    f"max_daily_loss {lim.max_daily_loss:.4f}"
                ),
                limits=lim,
                explainer=explainer,
                var=var_result.var,
                drawdown=drawdown,
                metrics=metrics,
                metadata=meta,
            )

    if var_result.var > lim.max_portfolio_var:
        return _decision(
            approved=False,
            stage="post_trade",
            reason=(
                f"portfolio VaR {var_result.var:.4f} exceeds "
                f"max_portfolio_var {lim.max_portfolio_var:.4f}"
            ),
            limits=lim,
            explainer=explainer,
            var=var_result.var,
            drawdown=drawdown,
            metrics=metrics,
            metadata=meta,
        )

    if drawdown > lim.max_drawdown:
        return _decision(
            approved=False,
            stage="post_trade",
            reason=f"drawdown {drawdown:.4f} exceeds max_drawdown {lim.max_drawdown:.4f}",
            limits=lim,
            explainer=explainer,
            var=var_result.var,
            drawdown=drawdown,
            metrics=metrics,
            metadata=meta,
        )

    return _decision(
        approved=True,
        stage="post_trade",
        reason="post-trade quant checks passed",
        limits=lim,
        explainer=explainer,
        var=var_result.var,
        drawdown=drawdown,
        metrics=metrics,
        metadata=meta,
    )


def evaluate_risk(
    *,
    order_symbol: str,
    proposed_weight: float,
    portfolio: Portfolio,
    historical_returns: ReturnSeries,
    prices: PriceSeries | None = None,
    limits: QuantRiskLimits | None = None,
) -> QuantRiskDecision:
    """Full evaluate_risk entrypoint used by Control Plane / API."""
    return pre_trade_check(
        order_symbol=order_symbol,
        proposed_weight=proposed_weight,
        portfolio=portfolio,
        historical_returns=historical_returns,
        limits=limits,
        prices=prices,
    )


def _with_weight(portfolio: Portfolio, symbol: str, weight: float) -> Portfolio:
    positions = [p.model_copy() for p in portfolio.positions]
    found = False
    for pos in positions:
        if pos.symbol == symbol:
            pos.weight = weight
            found = True
            break
    if not found:
        positions.append(PortfolioPositionWeights(symbol=symbol, weight=weight))
    return portfolio.model_copy(update={"positions": positions})


def _decision(
    *,
    approved: bool,
    stage: str,
    reason: str,
    limits: QuantRiskLimits,
    explainer: RiskExplainer,
    var: float | None = None,
    drawdown: float | None = None,
    metrics=None,
    metadata: dict[str, Any] | None = None,
) -> QuantRiskDecision:
    decision = QuantRiskDecision(
        approved=approved,
        stage=stage,
        reason=reason,
        var=var,
        drawdown=drawdown,
        metrics=metrics,
        metadata={
            **(metadata or {}),
            "enforce": limits.enforce,
            "soft_pass": (not approved) and (not limits.enforce),
        },
    )
    decision.explanation = explainer.explain_decision(decision)
    return decision
