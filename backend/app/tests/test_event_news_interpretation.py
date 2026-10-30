"""Tests for deterministic event/news interpretation (OFAC license extension)."""
from __future__ import annotations

from app.services.chat.advisor_prompt import synthesize_event_answer
from app.services.chat.event_news_interpretation import (
    interpret_event_news,
    is_ofac_license_extension_scenario,
    mentions_carlyle,
)
from app.services.chat.llm_advisor import _build_rag_context
from app.services.chat.deep_advisor import AdvisorContext, compose_deep_reply
from app.services.analysis.context import AnalysisContext
from app.services.analysis.ticker_payload import assemble_ticker_analysis_payload
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


def _lkoh_headline() -> str:
    return (
        "US Treasury extends license for Lukoil International GmbH; Carlyle stake in focus"
    )


def _lkoh_question() -> str:
    return (
        "Как продление лицензии Минфина США на Lukoil International и Carlyle "
        "повлияет на LKOH?"
    )


def test_ofac_extension_pattern_detected():
    headline = _lkoh_headline()
    question = _lkoh_question()
    assert is_ofac_license_extension_scenario(question=question, headlines=[headline])
    assert mentions_carlyle(question=question, headlines=[headline])


def test_interpretation_positive_short_term_bias():
    interp = interpret_event_news(
        question=_lkoh_question(),
        headlines=[_lkoh_headline()],
        ticker="LKOH",
    )
    assert interp is not None
    assert interp.short_term_bias == "moderately_positive_short_term"
    lead = interp.lead_paragraph_ru(ticker="LKOH", headline=_lkoh_headline())
    lower = lead.lower()
    assert "позитив" in lower or "relief" in lower
    assert "carlyle" in lower or "опциональ" in lower
    assert "умеренное снижение" not in lower


def test_synthesize_event_answer_uses_rubric_not_model_decline():
    headline = _lkoh_headline()
    outlook = "Краткий outlook модели по LKOH: направление «умеренное снижение» на ~7д."
    text = synthesize_event_answer(
        _lkoh_question(),
        ticker="LKOH",
        headlines=(headline,),
        outlook_line=outlook,
        model_outlook_appendix="Справочно: интервал -3%…+6%.",
    )
    lower = text.lower()
    assert "умеренное снижение" not in lower
    assert "позитив" in lower or "relief" in lower
    assert "carlyle" in lower or "сделк" in lower or "опциональ" in lower


def _down_lkoh_ctx():
    output = ForecastOutput(
        instrument_id=1,
        symbol="LKOH",
        as_of="2026-07-23T00:00:00Z",
        point_forecast=PointForecast(
            magnitude_class=PointMagnitudeClass.DOWN,
            expected_return_sign=-1,
            momentum_score=0.35,
        ),
        interval_forecast=IntervalForecast(
            horizon_days=7,
            p10=-0.08,
            p90=-0.01,
            rolling_volatility=0.022,
            confidence_multiplier=1.645,
        ),
        distribution_forecast=DistributionForecast(
            p5=-0.12,
            p25=-0.05,
            p50=-0.02,
            p75=0.0,
            p95=0.02,
            method="historical_percentile",
        ),
        scenario_forecast=ScenarioForecast(scenarios=(), scenario_dispersion=0.02),
        risk_forecast=RiskForecastLayer(
            instrument_metrics={"composite_risk_score": 0.4},
            portfolio_metrics={},
            plain_language_summary="",
            risk_items=(),
        ),
        action_forecast=ActionForecast(
            recommendation=ActionRecommendation.HOLD,
            reason="test",
            rule_id="t",
        ),
        calibrated_confidence=0.5,
        high_confidence=False,
        instruction_block="",
        narrator_insights=(),
    )
    analysis = AnalysisContext(symbol="LKOH", factor_exposures={})
    payload = assemble_ticker_analysis_payload(output=output, analysis=analysis)
    from dataclasses import replace

    payload = replace(payload, news_titles=(_lkoh_headline(),))
    return AdvisorContext(output=output, analysis=analysis, payload=payload)


def test_compose_lkoh_license_extension_reply():
    ctx = _down_lkoh_ctx()
    reply = compose_deep_reply(question=_lkoh_question(), ctx=ctx)
    lower = reply.lower()
    assert "ml_score" not in lower
    assert "умеренное снижение" not in lower
    assert "позитив" in lower or "relief" in lower
    assert "carlyle" in lower or "опциональ" in lower or "сделк" in lower


def test_rag_context_includes_interpretation_hints_without_ml_score():
    ctx = _down_lkoh_ctx()
    rag = _build_rag_context(_lkoh_question(), ctx)
    assert "Подсказки интерпретации события" in rag
    assert "moderately_positive_short_term" in rag
    assert "ml_score (контекст" not in rag.lower()
