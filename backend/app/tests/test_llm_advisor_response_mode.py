"""Regression: in-app chat LLM prompts — direct prose default, not forced [1]…[7]."""
from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.analysis.context import AnalysisContext
from app.services.analysis.ticker_payload import assemble_ticker_analysis_payload
from app.services.chat.advisor_prompt import (
    build_senior_analyst_llm_system,
    headlines_matching_question,
    senior_analyst_user_prompt,
    use_structured_analyst_format,
    wants_brief_direct_answer,
)
from app.services.chat.deep_advisor import AdvisorContext, finalize_advisor_reply
from app.services.chat.llm_advisor import (
    _INAPP_CHAT_MAX_TOKENS,
    _build_rag_context,
    try_llm_senior_analyst_answer,
)
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


def _ctx() -> AdvisorContext:
    output = ForecastOutput(
        instrument_id=1,
        symbol="NVDA",
        as_of="2026-07-23T00:00:00Z",
        point_forecast=PointForecast(
            magnitude_class=PointMagnitudeClass.UP,
            expected_return_sign=1,
            momentum_score=0.7,
            plain_language_summary="Moderate upside bias on horizon.",
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
            instrument_metrics={"cvar_95": 0.11, "beta": 1.2},
            portfolio_metrics={},
            plain_language_summary="Elevated tail risk vs sector.",
            risk_items=(),
        ),
        action_forecast=ActionForecast(
            recommendation=ActionRecommendation.HOLD,
            reason="Range-bound with positive skew",
            rule_id="t",
        ),
        calibrated_confidence=0.62,
        high_confidence=False,
        instruction_block="",
        narrator_insights=(),
    )
    analysis = AnalysisContext(symbol="NVDA", factor_exposures={"momentum": 0.5})
    payload = assemble_ticker_analysis_payload(output=output, analysis=analysis)
    payload = replace(payload, ml_score=0.71, news_titles=("NVDA data center demand strong",))
    return AdvisorContext(output=output, analysis=analysis, payload=payload)


def test_simple_question_uses_direct_mode_not_seven_sections():
    q = "Почему у NVDA такой прогноз на неделю?"
    assert use_structured_analyst_format(q) is False
    system = build_senior_analyst_llm_system(structured=False)
    assert "[1] Прямой ответ" not in system
    assert "Не используй обязательный формат [1]…[7]" in system
    user = senior_analyst_user_prompt(structured=False)
    assert "[1]" not in user
    assert "развёрнуто" in user.lower() or "развернуто" in user.lower()


def test_full_breakdown_requests_structured_format():
    q = "Дай полный детальный разбор NVDA"
    assert use_structured_analyst_format(q) is True
    system = build_senior_analyst_llm_system(structured=True)
    assert "[7] Итоговый вердикт" in system
    user = senior_analyst_user_prompt(structured=True)
    assert "[1]" in user and "[7]" in user


def test_spy_brief_question_uses_brief_prompt_not_structured():
    q = "Почему такой прогноз по SPY на неделю? Ответь прямо, без полного шаблона."
    assert wants_brief_direct_answer(q) is True
    assert use_structured_analyst_format(q) is False
    system = build_senior_analyst_llm_system(structured=False, brief=True)
    assert "ПРИОРИТЕТ ИНСТРУКЦИИ ПОЛЬЗОВАТЕЛЯ" in system
    assert "2–4 предложения" in system
    user = senior_analyst_user_prompt(structured=False, brief=True)
    assert "кратко" in user.lower()
    assert "развёрнуто" not in user.lower()


def test_finalize_advisor_reply_strips_duplicated_llm_block():
    from app.services.chat.advisor_prompt import has_repeated_substring

    block = (
        "VaR 95%: 8.0% — оценка дневного убытка. CVaR 95%: 11.0% — хвостовой риск. "
        "ml_score модели: 65%. SHAP: моментум +0.10."
    )
    duplicated = f"{block}\n\n{block}"
    out = finalize_advisor_reply(duplicated)
    assert not has_repeated_substring(out, min_len=50)
    assert out.count("ml_score модели") == 1


def test_rule_fallback_uses_direct_prose_not_numbered_sections():
    from app.services.chat.deep_advisor import compose_direct_analyst_reply

    ctx = _ctx()
    q = "Почему у NVDA такой прогноз на неделю?"
    out = compose_direct_analyst_reply(question=q, ctx=ctx, prior_messages=())
    assert "[1]" not in out and "[7]" not in out
    assert "NVDA" in out.upper() or "nvda" in out.lower()
    assert out.split("\n\n", 1)[0].startswith("На горизонте")
    assert "Структура рынка" not in out
    assert out.count("ml_score модели") <= 1


def test_rule_fallback_answers_event_without_news_refusal():
    from dataclasses import replace

    from app.services.chat.deep_advisor import compose_direct_analyst_reply

    ctx = _ctx()
    ctx = AdvisorContext(
        output=ctx.output,
        analysis=ctx.analysis,
        payload=replace(ctx.payload, news_titles=()),
    )
    out = compose_direct_analyst_reply(
        question="Как отсутствие свежих новостей влияет на NVDA?",
        ctx=ctx,
        prior_messages=(),
    )
    first = out.split("\n\n", 1)[0].lower()
    assert "нет заголов" in first or "снимке" in first
    assert "модель" in out.lower() and "интервал" in out.lower()
    assert "не могу" not in out.lower()


def test_rag_context_includes_forecast_and_distribution():
    ctx = _ctx()
    rag = _build_rag_context("Какой прогноз у NVDA?", ctx)
    assert "P50" in rag or "Распределение" in rag
    assert "ml_score" in rag
    assert "direct prose" in rag


def test_corporate_geo_question_excludes_irrelevant_headlines():
    q = (
        "Как повлияет перенос штаб-квартиры Amazon из Сиэтла в Даллас "
        "на стоимость акций AMZN?"
    )
    headlines = (
        "Workers strike at Amazon data center project in Bahrain",
        "Amazon reports AWS revenue beat",
    )
    matched = headlines_matching_question(q, headlines)
    assert matched == []


def test_corporate_geo_rag_forbids_random_ticker_news():
    from dataclasses import replace

    ctx = _ctx()
    ctx = AdvisorContext(
        output=replace(ctx.output, symbol="AMZN"),
        analysis=replace(ctx.analysis, symbol="AMZN"),
        payload=replace(
            ctx.payload,
            ticker="AMZN",
            news_titles=(
                "Workers strike at Amazon data center project in Bahrain",
            ),
        ),
    )
    rag = _build_rag_context(
        "Как повлияет перенос штаб-квартиры из Сиэтла в Даллас на AMZN?",
        ctx,
    )
    assert "Bahrain" not in rag
    assert "Запрещено цитировать прочие новости" in rag


def test_corporate_geo_rule_fallback_lead_not_random_headline():
    from dataclasses import replace

    from app.services.chat.deep_advisor import compose_direct_analyst_reply

    ctx = _ctx()
    ctx = AdvisorContext(
        output=replace(ctx.output, symbol="AMZN"),
        analysis=replace(ctx.analysis, symbol="AMZN"),
        payload=replace(
            ctx.payload,
            ticker="AMZN",
            news_titles=(
                "Workers strike at Amazon data center project in Bahrain",
            ),
        ),
    )
    q = "Как повлияет перенос штаб-квартиры из Сиэтла в Даллас на AMZN?"
    out = compose_direct_analyst_reply(question=q, ctx=ctx, prior_messages=())
    assert "Bahrain" not in out
    assert "штаб-квартир" in out.lower() or "hq" in out.lower()


@pytest.mark.asyncio
async def test_llm_call_uses_direct_system_for_simple_question(monkeypatch):
    ctx = _ctx()
    captured: dict = {}

    async def fake_complete(task_name, prompt, **kwargs):
        captured["task_name"] = task_name
        captured["prompt"] = prompt
        captured.update(kwargs)
        return "Развёрнутый ответ по NVDA с опорой на интервал прогноза."

    monkeypatch.setattr("app.core.config.settings.LLM_ENABLED", True)
    monkeypatch.setattr("app.services.llm.llm_service.llm_enabled", lambda: True)
    monkeypatch.setattr("app.services.llm.llm_service.LLMService.complete", fake_complete)

    out = await try_llm_senior_analyst_answer("Что означает прогноз NVDA на 7 дней?", ctx)
    assert out and "NVDA" in out
    system = captured.get("system") or ""
    assert "[1] Прямой ответ" not in system
    assert captured.get("max_tokens") == _INAPP_CHAT_MAX_TOKENS
    assert captured.get("temperature", 0) >= 0.4
    assert "[1]" not in captured.get("prompt", "")


@pytest.mark.asyncio
async def test_llm_call_uses_brief_tokens_for_spy_question(monkeypatch):
    ctx = _ctx()
    captured: dict = {}

    async def fake_complete(task_name, prompt, **kwargs):
        captured.update(kwargs)
        return "Краткий ответ по SPY: умеренный рост на неделю из-за моментума."

    monkeypatch.setattr("app.core.config.settings.LLM_ENABLED", True)
    monkeypatch.setattr("app.services.llm.llm_service.llm_enabled", lambda: True)
    monkeypatch.setattr("app.services.llm.llm_service.LLMService.complete", fake_complete)

    q = "Почему такой прогноз по SPY на неделю? Ответь прямо, без полного шаблона."
    out = await try_llm_senior_analyst_answer(q, ctx)
    assert out and "SPY" in out
    assert captured.get("max_tokens") == 1200
    assert "ПРИОРИТЕТ" in (captured.get("system") or "")


@pytest.mark.asyncio
async def test_build_deep_dedupes_duplicated_llm_answer(monkeypatch):
    from app.services.chat.advisor_prompt import has_repeated_substring
    from app.services.chat.deep_advisor import build_deep_advisor_reply

    ctx = _ctx()
    block = (
        "VaR 95%: 8.0% — оценка дневного убытка. CVaR 95%: 11.0% — хвостовой риск. "
        "ml_score модели: 65%. SHAP: моментум +0.10."
    )

    async def fake_gather(*_args, **_kwargs):
        return ctx

    async def fake_llm(*_args, **_kwargs):
        return f"{block}\n\n{block}"

    monkeypatch.setattr("app.core.config.settings.LLM_ENABLED", True)
    monkeypatch.setattr("app.core.config.settings.CHAT_DEBUG_FOOTERS", False)
    monkeypatch.setattr("app.core.config.settings.CHAT_SHOW_DISCLOSURE", False)
    monkeypatch.setattr("app.services.chat.deep_advisor.gather_advisor_context", fake_gather)
    monkeypatch.setattr("app.services.chat.llm_advisor.try_llm_senior_analyst_answer", fake_llm)

    out = await build_deep_advisor_reply(
        None,  # type: ignore[arg-type]
        instrument_id=1,
        symbol="SPY",
        user_question="Почему такой прогноз по SPY на неделю? Ответь прямо, без полного шаблона.",
        prior_messages=(),
    )
    assert not has_repeated_substring(out, min_len=50)
    assert out.count("ml_score модели") == 1


@pytest.mark.asyncio
async def test_successful_llm_reply_hides_source_footer_and_disclosure(monkeypatch):
    from app.services.chat.deep_advisor import build_deep_advisor_reply

    ctx = _ctx()

    async def fake_gather(*_args, **_kwargs):
        return ctx

    async def fake_llm(*_args, **_kwargs):
        return "Прямой ответ Kimi по NVDA без служебных футеров."

    monkeypatch.setattr("app.core.config.settings.LLM_ENABLED", True)
    monkeypatch.setattr("app.core.config.settings.CHAT_DEBUG_FOOTERS", False)
    monkeypatch.setattr("app.core.config.settings.CHAT_SHOW_DISCLOSURE", False)
    monkeypatch.setattr("app.services.chat.deep_advisor.gather_advisor_context", fake_gather)
    monkeypatch.setattr("app.services.chat.llm_advisor.try_llm_senior_analyst_answer", fake_llm)

    out = await build_deep_advisor_reply(
        None,  # type: ignore[arg-type]
        instrument_id=1,
        symbol="NVDA",
        user_question="Стоит ли покупать NVDA?",
        prior_messages=(),
    )
    assert out == "Прямой ответ Kimi по NVDA без служебных футеров."
    assert "Источник:" not in out
    assert "не инвестиционная рекомендация" not in out.lower()
