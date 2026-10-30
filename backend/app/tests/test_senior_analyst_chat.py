"""Senior analyst structured ticker chat — non-template answers."""
from __future__ import annotations

from dataclasses import replace

from app.services.analysis.context import AnalysisContext
from app.services.analysis.ticker_payload import assemble_ticker_analysis_payload
from app.services.chat.advisor_prompt import SENIOR_ANALYST_SYSTEM_RU, senior_analyst_intent_hint
from app.services.chat.deep_advisor import AdvisorContext, compose_deep_reply
from app.services.prediction_hierarchy.types import (
    ActionForecast,
    ActionRecommendation,
    DistributionForecast,
    ForecastOutput,
    IntervalForecast,
    PointForecast,
    PointMagnitudeClass,
    RiskForecastLayer,
    ScenarioForecast,
)


def _nvda_ctx(*, headlines: tuple[str, ...] = ()) -> AdvisorContext:
    output = ForecastOutput(
        instrument_id=1,
        symbol="NVDA",
        as_of="2026-07-23T00:00:00Z",
        point_forecast=PointForecast(
            magnitude_class=PointMagnitudeClass.UP,
            expected_return_sign=1,
            momentum_score=0.7,
        ),
        interval_forecast=IntervalForecast(
            horizon_days=7,
            p10=-0.02,
            p90=0.08,
            rolling_volatility=0.025,
            confidence_multiplier=1.645,
        ),
        distribution_forecast=DistributionForecast(
            p5=-0.05,
            p25=0.0,
            p50=0.03,
            p75=0.05,
            p95=0.1,
            method="historical_percentile",
        ),
        scenario_forecast=ScenarioForecast(scenarios=(), scenario_dispersion=0.02),
        risk_forecast=RiskForecastLayer(
            instrument_metrics={"cvar_95": 0.11},
            portfolio_metrics={},
            plain_language_summary="",
            risk_items=(),
        ),
        action_forecast=ActionForecast(
            recommendation=ActionRecommendation.HOLD,
            reason="test",
            rule_id="t",
        ),
        calibrated_confidence=0.62,
        high_confidence=False,
        instruction_block="",
        narrator_insights=(),
    )
    analysis = AnalysisContext(symbol="NVDA", factor_exposures={"momentum": 0.5})
    payload = assemble_ticker_analysis_payload(output=output, analysis=analysis)
    payload = replace(
        payload,
        ml_score=0.71,
        news_titles=headlines,
    )
    return AdvisorContext(output=output, analysis=analysis, payload=payload)


def test_senior_analyst_system_prompt_verbatim_anchor():
    assert SENIOR_ANALYST_SYSTEM_RU.startswith(
        "Ты — senior buy-side equity research analyst, market strategist"
    )
    assert "где реальный сигнал." in SENIOR_ANALYST_SYSTEM_RU
    assert "[7] Итоговый вердикт" in SENIOR_ANALYST_SYSTEM_RU
    assert "A) DIRECT ANSWER" in SENIOR_ANALYST_SYSTEM_RU
    assert "G) ACTIONABILITY" in SENIOR_ANALYST_SYSTEM_RU


def test_logistics_question_not_generic_ml_opener():
    ctx = _nvda_ctx(
        headlines=(
            "Nvidia warns Taiwan packaging constraints may extend lead times",
        ),
    )
    q = "Как логистика Taiwan влияет на NVDA?"
    reply = compose_deep_reply(question=q, ctx=ctx)
    lower = reply.lower()
    assert "taiwan" in lower or "логист" in lower or "supply" in lower or "data gap" in lower
    assert not reply.strip().lower().startswith("ml_score")
    generic_buy = compose_deep_reply(
        question="Стоит ли купить NVDA на $50?",
        ctx=ctx,
    )
    assert reply != generic_buy
    assert senior_analyst_intent_hint(q).lower().find("logistics") >= 0


def test_gazp_investment_program_context():
    headline = "Газпром сокращает инвестпрограмму на 515 млрд рублей — фокус на FCF"
    output = replace(
        _nvda_ctx().output,
        symbol="GAZP",
    )
    analysis = AnalysisContext(symbol="GAZP", factor_exposures={})
    payload = replace(
        assemble_ticker_analysis_payload(output=output, analysis=analysis),
        news_titles=(headline,),
    )
    ctx = AdvisorContext(output=output, analysis=analysis, payload=payload)
    q = "Как сокращение инвестпрограммы на 515 млрд повлияет на GAZP?"
    reply = compose_deep_reply(question=q, ctx=ctx)
    lower = reply.lower()
    assert "515" in lower or "инвестпрограм" in lower or "fcf" in lower
    assert "[1]" not in reply


def test_two_questions_same_ticker_differ():
    ctx = _nvda_ctx(headlines=("NVDA data center demand remains strong",))
    logistics = compose_deep_reply(
        question="Как Taiwan logistics влияет на NVDA?",
        ctx=ctx,
    )
    buy = compose_deep_reply(
        question="Стоит ли купить NVDA на $50?",
        ctx=ctx,
    )
    assert logistics != buy
    logistics_body = logistics.split("\n\n", 1)[0]
    buy_body = buy.split("\n\n", 1)[0]
    assert logistics_body.strip() != buy_body.strip()
