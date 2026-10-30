"""Unit tests for deep ticker advisor — Section 7.1 payload-grounded replies."""
from __future__ import annotations

from dataclasses import replace

from app.services.analysis.context import AnalysisContext
from app.services.analysis.ticker_payload import ShapFactor, TickerAnalysisPayload, assemble_ticker_analysis_payload
from app.services.chat.advisor_prompt import DISCLOSURE_RU, format_shap_plain_ru, headlines_matching_question
from app.services.chat.deep_advisor import (
    AdvisorContext,
    QuestionIntent,
    _direct_answer,
    _market_data_direct_answer,
    _structured_verdict_line,
    _was_shown,
    compose_deep_reply,
    finalize_advisor_reply,
    parse_market_data_subtype,
    parse_question_intent,
    primary_intent,
)
from app.services.prediction_hierarchy.types import (
    ActionForecast,
    ActionRecommendation,
    DistributionForecast,
    ForecastOutput,
    IntervalForecast,
    NarratorInsight,
    PointForecast,
    PointMagnitudeClass,
    RiskForecastLayer,
    RiskItem,
    ScenarioForecast,
    ScenarioForecastItem,
)


def _sample_analysis(*, symbol: str = "AMZN", factor_exposures: dict[str, float] | None = None) -> AnalysisContext:
    return AnalysisContext(
        symbol=symbol,
        factor_exposures=factor_exposures or {"momentum": 0.42, "market_beta": 1.15},
    )


def _sample_output(
    *,
    action: ActionRecommendation = ActionRecommendation.HOLD,
    instruction_block: str = "",
    risk_items: tuple[RiskItem, ...] = (),
    calibrated_confidence: float = 0.72,
    scenarios: tuple[ScenarioForecastItem, ...] = (),
    narrator_insights: tuple[NarratorInsight, ...] = (),
) -> ForecastOutput:
    return ForecastOutput(
        instrument_id=1,
        symbol="AMZN",
        as_of="2026-07-23T00:00:00Z",
        point_forecast=PointForecast(
            magnitude_class=PointMagnitudeClass.UP,
            expected_return_sign=1,
            momentum_score=0.55,
        ),
        interval_forecast=IntervalForecast(
            horizon_days=7,
            p10=-0.03,
            p90=0.06,
            rolling_volatility=0.018,
            confidence_multiplier=1.645,
        ),
        distribution_forecast=DistributionForecast(
            p5=-0.08,
            p25=-0.01,
            p50=0.02,
            p75=0.04,
            p95=0.09,
            method="historical_percentile",
        ),
        scenario_forecast=ScenarioForecast(scenarios=scenarios, scenario_dispersion=0.02),
        risk_forecast=RiskForecastLayer(
            instrument_metrics={
                "composite_risk_score": 0.35,
                "volatility_expansion_probability": 0.42,
                "liquidity_risk_score": 0.28,
                "tail_risk_score": 0.31,
                "cvar_95": 0.14,
            },
            portfolio_metrics={},
            plain_language_summary="Умеренный риск по волатильности.",
            risk_items=risk_items or (
                RiskItem(
                    metric="volatility_expansion_probability",
                    score=0.42,
                    severity="medium",
                    plain_language_summary="Расширение волатильности: 42% — повышенное внимание",
                ),
                RiskItem(
                    metric="tail_risk_score",
                    score=0.31,
                    severity="medium",
                    plain_language_summary="Хвостовой риск: 31% — повышенное внимание",
                ),
                RiskItem(
                    metric="liquidity_risk_score",
                    score=0.28,
                    severity="low",
                    plain_language_summary="Ликвидность: 28% — в пределах нормы",
                ),
            ),
        ),
        action_forecast=ActionForecast(
            recommendation=action,
            reason="balanced risk and momentum",
            rule_id="test_rule",
        ),
        calibrated_confidence=calibrated_confidence,
        high_confidence=False,
        instruction_block=instruction_block,
        narrator_insights=narrator_insights,
    )


def _sample_ctx(**kwargs) -> AdvisorContext:
    output = kwargs.pop("output", _sample_output())
    analysis = kwargs.pop("analysis", _sample_analysis(symbol=output.symbol))
    fundamentals = kwargs.pop("fundamentals", {})
    payload = kwargs.pop("payload", None)
    if payload is None:
        payload = assemble_ticker_analysis_payload(
            output=output,
            analysis=analysis,
            fundamentals=fundamentals,
        )
    news_headlines = kwargs.pop("news_headlines", None)
    if news_headlines is not None:
        payload = replace(payload, news_titles=tuple(news_headlines))
    return AdvisorContext(
        output=output,
        analysis=analysis,
        payload=payload,
        fundamentals=fundamentals,
        news_headlines=list(news_headlines or ()),
        **kwargs,
    )


def test_parse_question_intent_buy():
    intent = parse_question_intent("Стоит ли покупать AMZN на неделю?")
    assert intent & QuestionIntent.BUY
    assert intent & QuestionIntent.TIMEFRAME


def test_parse_question_intent_risk():
    intent = parse_question_intent("Какой риск по AMZN?")
    assert intent & QuestionIntent.RISK
    assert primary_intent(intent) == QuestionIntent.RISK


def test_parse_question_intent_market_cap():
    intent = parse_question_intent("Какая капитализация GAZP?")
    assert intent & QuestionIntent.MARKET_DATA
    assert primary_intent(intent) == QuestionIntent.MARKET_DATA
    assert parse_market_data_subtype("Какая капитализация GAZP?") == "market_cap"


def test_parse_question_intent_regulatory():
    intent = parse_question_intent("Какие регуляторные риски у SBER?")
    assert intent & QuestionIntent.REGULATORY
    assert intent & QuestionIntent.RISK


def test_parse_question_intent_general_fallback():
    intent = parse_question_intent("Расскажи про AMZN")
    assert intent == QuestionIntent.GENERAL


def test_was_shown_detects_substring():
    prior = ("По вашему вопросу «стоит ли покупать?»: ml_score модели: 72%",)
    assert _was_shown("ml_score модели: 72%", prior, min_len=10)


def test_market_cap_answer_with_data():
    output = replace(_sample_output(), symbol="GAZP")
    ctx = _sample_ctx(
        output=output,
        analysis=_sample_analysis(symbol="GAZP"),
        fundamentals={"market_cap": 4_500_000_000_000, "exchange": "MOEX"},
    )
    answer = _market_data_direct_answer("Какая капитализация GAZP?", ctx)
    assert "GAZP" in answer
    assert "4.50 трлн" in answer
    assert "недоступн" not in answer.lower()


def test_market_cap_answer_missing_data():
    ctx = _sample_ctx(fundamentals={})
    answer = _market_data_direct_answer("Какая капитализация GAZP?", ctx)
    assert "недоступн" in answer.lower()
    assert "сократите" not in answer.lower()
    assert "риск" not in answer.lower() or "недоступн" in answer.lower()


def test_market_cap_question_not_risk_fallback():
    ctx = _sample_ctx(
        output=_sample_output(action=ActionRecommendation.REDUCE_SIZE),
        fundamentals={},
    )
    reply = compose_deep_reply(question="Какая капитализация GAZP?", ctx=ctx)
    assert "недоступн" in reply.lower() or "капитализац" in reply.lower()
    assert primary_intent(parse_question_intent("Какая капитализация GAZP?")) == QuestionIntent.MARKET_DATA
    assert "купить" not in reply.lower()
    assert "рекомендация купить" not in reply.lower()


def test_no_buy_advice_on_buy_question():
    ctx = _sample_ctx(output=_sample_output(action=ActionRecommendation.ENTER_SMALL_SIZE))
    reply = compose_deep_reply(question="Стоит ли покупать AMZN?", ctx=ctx)
    assert "По вашему вопросу" not in reply
    assert "[1]" not in reply
    assert not reply.lstrip().lower().startswith("ml_score")
    assert "без прямой рекомендации" in reply.lower() or "без рекомендации" in reply.lower()
    assert DISCLOSURE_RU in reply


def test_compose_no_question_echo_prefix():
    ctx = _sample_ctx()
    reply = compose_deep_reply(question="Какие события по GAZP?", ctx=ctx)
    assert not reply.startswith("По вашему вопросу")


def test_news_lists_all_headlines_structured():
    from app.services.chat.advisor_prompt import format_news_from_payload

    titles = tuple(f"Headline {i} about GAZP earnings" for i in range(7))
    text = format_news_from_payload(titles)
    assert "+ ещё" not in text
    assert "Headline 0" in text
    assert "Headline 6" in text
    assert "Корпоративные и финансовые:" in text

    ctx = _sample_ctx(news_headlines=list(titles))
    reply = compose_deep_reply(
        question="Какие новости по GAZP? Дай подробный разбор.",
        ctx=ctx,
    )
    assert "+ ещё" not in reply
    assert "Headline 0" in reply
    assert "[3]" in reply


def test_disclosure_once_per_conversation():
    ctx = _sample_ctx()
    first = compose_deep_reply(question="Стоит ли покупать AMZN?", ctx=ctx)
    assert DISCLOSURE_RU in first
    second = compose_deep_reply(
        question="А продавать?",
        ctx=ctx,
        prior_messages=(first,),
    )
    assert DISCLOSURE_RU not in second


def test_shap_plain_language():
    factors = (
        ShapFactor(feature="momentum_12m", contribution=0.34),
        ShapFactor(feature="value", contribution=-0.12),
    )
    text = format_shap_plain_ru(factors)
    assert "12-месячный моментум" in text
    assert "shap_value" not in text.lower()
    assert "0.34" in text


def test_compose_shap_question_uses_payload():
    output = _sample_output(
        narrator_insights=(
            NarratorInsight(
                template_id="t1",
                text_ru="Моментум поддерживает скор.",
                text_en="",
                source_metric="momentum_12m",
                source_value=0.34,
            ),
        )
    )
    analysis = _sample_analysis()
    payload = replace(
        assemble_ticker_analysis_payload(output=output, analysis=analysis),
        shap_top_factors=(
            ShapFactor(feature="momentum_12m", contribution=0.34),
            ShapFactor(feature="value", contribution=-0.08),
        ),
        shap_available=True,
    )
    ctx = _sample_ctx(output=output, payload=payload)
    reply = compose_deep_reply(question="Почему такой score у AMZN?", ctx=ctx)
    assert "моментум" in reply.lower()
    assert "ml_score" in reply.lower()


def test_conflict_surfacing_high_score_high_cvar():
    output = _sample_output(calibrated_confidence=0.78)
    analysis = _sample_analysis()
    payload = assemble_ticker_analysis_payload(output=output, analysis=analysis, fundamentals={"beta": 1.0})
    payload = replace(
        payload,
        ml_score=0.78,
        risk_metrics={**payload.risk_metrics, "cvar_95": 0.16},
    )
    ctx = _sample_ctx(output=output, payload=payload)
    reply = compose_deep_reply(question="Расскажи про AMZN", ctx=ctx)
    assert "CVaR" in reply or "cvar" in reply.lower() or "хвостов" in reply.lower()


def test_compose_includes_news_from_payload():
    ctx = _sample_ctx(news_headlines=["Amazon announces new AI chip"])
    reply = compose_deep_reply(
        question="Какие новости по AMZN? Дай подробный разбор.",
        ctx=ctx,
    )
    assert "Amazon announces new AI chip" in reply


def test_event_question_leads_with_prose_not_metric_dump():
    headline = (
        "US Treasury extends license for Lukoil International GmbH; Carlyle stake in focus"
    )
    output = replace(
        _sample_output(),
        symbol="LKOH",
        point_forecast=PointForecast(
            magnitude_class=PointMagnitudeClass.DOWN,
            expected_return_sign=-1,
            momentum_score=0.35,
        ),
    )
    ctx = _sample_ctx(
        output=output,
        analysis=_sample_analysis(symbol="LKOH"),
        news_headlines=[headline],
    )
    reply = compose_deep_reply(
        question="Как продление лицензии Минфина США на Lukoil International и Carlyle повлияет на LKOH?",
        ctx=ctx,
    )
    lower = reply.lower()
    assert "ml_score" not in lower
    assert "shap" not in lower
    assert "var" not in lower
    assert "умеренное снижение" not in lower
    assert "позитив" in lower or "relief" in lower
    assert "carlyle" in lower or "лиценз" in lower or "опциональ" in lower
    assert headline[:20] in reply or "Lukoil" in reply


def test_amzn_hq_question_does_not_cite_bahrain_strike():
    question = "Как повлияет перенос штаб-квартиры из Сиэтла в Даллас на стоимость акций?"
    bahrain = "KSIR strike on Amazon data center in Bahrain disrupts cloud services"
    ctx = _sample_ctx(news_headlines=[bahrain])

    assert headlines_matching_question(question, (bahrain,)) == []

    reply = compose_deep_reply(question=question, ctx=ctx)
    lower = reply.lower()
    assert "bahrain" not in lower
    assert "ksir" not in lower
    assert "нет заголовка" in lower or "нет заголовков" in lower
    assert "интервал" in lower


def test_amzn_hq_rag_omits_unmatched_bahrain_headline():
    from app.services.chat.llm_advisor import _build_rag_context

    question = "Как повлияет перенос штаб-квартиры из Сиэтла в Даллас на стоимость акций?"
    bahrain = "KSIR strike on Amazon data center in Bahrain disrupts cloud services"
    ctx = _sample_ctx(news_headlines=[bahrain])

    rag = _build_rag_context(question, ctx)
    lower = rag.lower()
    assert "bahrain" not in lower
    assert "ksir" not in lower
    assert "тематически совпадающих заголовков нет" in lower


def test_compose_risk_breakdown_includes_sections():
    ctx = _sample_ctx()
    reply = compose_deep_reply(
        question="Какой риск по AMZN? Дай подробный разбор.",
        ctx=ctx,
    )
    assert "[5]" in reply
    assert "риск" in reply.lower()


def test_direct_forecast_does_not_duplicate_risk_metrics():
    ctx = _sample_ctx()
    reply = compose_deep_reply(question="Почему такой прогноз по AMZN на неделю?", ctx=ctx)
    assert "[1]" not in reply
    assert reply.count("VaR 95%") <= 1
    assert reply.count("CVaR 95%") <= 1
    assert reply.count("ml_score модели") <= 1


def test_compose_general_breakdown_includes_sections():
    ctx = _sample_ctx(
        news_headlines=["Amazon Q2 earnings beat estimates"],
        macro_snippet="Макро-фон: VIX 18.2; инфляция (CPI proxy) 3.1%.",
        fundamentals={"market_cap": 1_900_000_000_000, "pe_ratio": 42.5, "beta": 1.2},
        quote={"price": 198.50, "change_pct": 1.2, "source": "yfinance"},
    )
    reply = compose_deep_reply(question="Расскажи про AMZN — полный разбор", ctx=ctx)
    assert "[1]" in reply
    assert "[5]" in reply
    assert "Amazon Q2 earnings beat estimates" in reply


def test_compose_regulatory_section_from_news():
    ctx = _sample_ctx(
        news_headlines=[
            "SEC opens investigation into Amazon accounting practices",
            "Amazon announces new AI chip",
        ],
    )
    reply = compose_deep_reply(
        question="Есть ли регуляторные заголовки по AMZN? Подробный разбор.",
        ctx=ctx,
    )
    assert "SEC" in reply


def test_scenario_names_shock_explicitly():
    scenarios = (
        ScenarioForecastItem(
            name="rate_shock_200bps",
            probability=0.22,
            impact=-0.11,
            label_ru="Шок ставок +200 б.п.",
        ),
    )
    ctx = _sample_ctx(output=_sample_output(scenarios=scenarios))
    reply = compose_deep_reply(
        question="Какой риск по AMZN? Полный разбор сценариев.",
        ctx=ctx,
    )
    assert "200" in reply or "став" in reply.lower()


def test_direct_answer_varies_on_follow_up():
    ctx = _sample_ctx()
    first = _direct_answer("Расскажи про AMZN", QuestionIntent.GENERAL, ctx)
    second = _direct_answer(
        "Расскажи про AMZN",
        QuestionIntent.GENERAL,
        ctx,
        prior_messages=(first,),
    )
    assert first != second
    assert "уточнение по вашему новому вопросу" not in second.lower()


def test_price_question_direct_answer():
    ctx = _sample_ctx(
        quote={"price": 150.25, "change_pct": -0.5, "source": "moex_iss"},
    )
    answer = _market_data_direct_answer("Какая цена GAZP?", ctx)
    assert "150.25" in answer
    assert "недоступн" not in answer.lower()


def test_dividend_question_no_raw_verdict_or_market_structure():
    ctx = _sample_ctx(
        output=replace(_sample_output(calibrated_confidence=0.36), symbol="LKOH"),
        fundamentals={"exchange": "MOEX", "source": "moex_iss"},
        macro_snippet="Макро-фон (РФ): инфляция (CPI) 3.5%; ключевая ставка ЦБ РФ 14.00%; Brent 89.0.",
    )
    reply = compose_deep_reply(question="Какая дивидендная доходность у LKOH?", ctx=ctx)
    assert "Negative | horizon" not in reply
    assert "confidence 36%" not in reply
    assert "Структура рынка по LKOH" not in reply
    assert "дивиденд" in reply.lower()


def test_structured_verdict_line_is_natural_language():
    ctx = _sample_ctx(output=_sample_output(calibrated_confidence=0.36))
    line = _structured_verdict_line(ctx, tone="Negative")
    assert "Negative |" not in line
    assert "horizon ~" not in line
    assert "аналитическая справка" in line.lower()


def test_finalize_strips_leaked_raw_verdict():
    raw = (
        "Данные о дивидендах недоступны.\n"
        "Negative | horizon ~10d | confidence 36% (аналитическая справка, не инвестиционная рекомендация)."
    )
    cleaned = finalize_advisor_reply(raw)
    assert "Negative | horizon" not in cleaned
    assert "confidence 36%" not in cleaned
    assert "дивиденд" in cleaned.lower()


def test_dividend_answer_with_history():
    ctx = _sample_ctx(
        output=replace(_sample_output(), symbol="LKOH"),
        fundamentals={
            "dividend_yield": 0.085,
            "dividend_history": [
                {"registry_close_date": "2024-07-08", "value": 541, "currency": "RUB"},
            ],
            "exchange": "MOEX",
            "source": "moex_iss",
        },
    )
    answer = _market_data_direct_answer("Какая дивидендная доходность LKOH?", ctx)
    assert "8.5%" in answer or "8,5%" in answer or "8.50%" in answer
    assert "541" in answer
