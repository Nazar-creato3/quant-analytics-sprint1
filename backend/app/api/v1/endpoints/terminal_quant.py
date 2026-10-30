"""Terminal Quant/Risk API — pure compute endpoints under /terminal/quant."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import get_current_user_email

from app.services.terminal_platform.quant.backtest import run_backtest, walk_forward
from app.services.terminal_platform.quant.explainer import RiskExplainer
from app.services.terminal_platform.quant.metrics import compute_risk_metrics
from app.services.terminal_platform.quant.models import (
    BacktestRequest,
    BacktestResult,
    EfficientFrontierResult,
    ExplainRequest,
    MetricsRequest,
    PortfolioOptRequest,
    PostTradeRequest,
    PreTradeRequest,
    QuantRiskDecision,
    RiskMetrics,
    StressRequest,
    StressResult,
    VaRRequest,
    VaRResult,
    WalkForwardRequest,
    WalkForwardResult,
)
from app.services.terminal_platform.quant.portfolio import efficient_frontier
from app.services.terminal_platform.quant.risk_manager import (
    evaluate_risk,
    post_trade_check,
    pre_trade_check,
)
from app.services.terminal_platform.quant.stress import shock_analysis, stress_scenario
from app.services.terminal_platform.quant.var import compute_var

router = APIRouter(prefix="/terminal/quant", tags=["terminal-quant"])
_explainer = RiskExplainer()
_auth = Depends(get_current_user_email)


@router.post("/metrics", response_model=RiskMetrics)
def api_metrics(body: MetricsRequest, _: str = _auth) -> RiskMetrics:
    return compute_risk_metrics(
        body.returns,
        prices=body.prices,
        benchmark_returns=body.benchmark_returns,
    )


@router.post("/var", response_model=VaRResult)
def api_var(body: VaRRequest, _: str = _auth) -> VaRResult:
    try:
        return compute_var(
            body.returns,
            body.confidence,
            method=body.method,
            n_simulations=body.n_simulations,
            seed=body.seed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/portfolio/frontier", response_model=EfficientFrontierResult)
def api_frontier(body: PortfolioOptRequest, _: str = _auth) -> EfficientFrontierResult:
    try:
        return efficient_frontier(
            body.expected_returns,
            body.cov_matrix,
            n_points=body.n_frontier_points,
            risk_free_rate=body.risk_free_rate,
            long_only=body.long_only,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/stress", response_model=StressResult)
def api_stress(body: StressRequest, _: str = _auth) -> StressResult:
    try:
        if body.scenario is not None:
            return stress_scenario(body.portfolio, body.scenario)
        assert body.shocks is not None
        return shock_analysis(body.portfolio, body.shocks)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/backtest", response_model=BacktestResult)
def api_backtest(body: BacktestRequest, _: str = _auth) -> BacktestResult:
    try:
        return run_backtest(body.prices, body.config)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/backtest/walk-forward", response_model=WalkForwardResult)
def api_walk_forward(body: WalkForwardRequest, _: str = _auth) -> WalkForwardResult:
    try:
        return walk_forward(
            body.prices,
            body.train_window,
            body.test_window,
            body.config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/risk/pre-trade", response_model=QuantRiskDecision)
def api_pre_trade(body: PreTradeRequest, _: str = _auth) -> QuantRiskDecision:
    return pre_trade_check(
        order_symbol=body.symbol,
        proposed_weight=body.proposed_weight,
        portfolio=body.portfolio,
        historical_returns=body.historical_returns,
        limits=body.limits,
        prices=body.prices,
    )


@router.post("/risk/post-trade", response_model=QuantRiskDecision)
def api_post_trade(body: PostTradeRequest, _: str = _auth) -> QuantRiskDecision:
    return post_trade_check(
        portfolio=body.portfolio,
        historical_returns=body.historical_returns,
        prices=body.prices,
        limits=body.limits,
    )


@router.post("/risk/evaluate", response_model=QuantRiskDecision)
def api_evaluate(body: PreTradeRequest, _: str = _auth) -> QuantRiskDecision:
    return evaluate_risk(
        order_symbol=body.symbol,
        proposed_weight=body.proposed_weight,
        portfolio=body.portfolio,
        historical_returns=body.historical_returns,
        prices=body.prices,
        limits=body.limits,
    )


@router.post("/explain")
def api_explain(body: ExplainRequest, _: str = _auth) -> dict[str, str]:
    text = _explainer.explain(
        metrics=body.metrics,
        var_result=body.var_result,
        decision=body.decision,
    )
    return {"explanation": text}
