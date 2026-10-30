"""Optional LLM layer for ticker chat (all questions with RAG context)."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.services.chat.advisor_prompt import (
    EVENT_QUESTION_RUBRIC_RU,
    NEWS_HEADLINE_CAP,
    _bucket_headlines_for_display,
    build_senior_analyst_llm_system,
    detect_score_conflicts,
    format_factor_exposure_user_ru,
    format_risk_with_context,
    format_scenario_with_shock,
    format_shap_plain_ru,
    headlines_matching_question,
    is_corporate_geo_question,
    is_event_question,
    senior_analyst_intent_hint,
    senior_analyst_user_prompt,
    use_structured_analyst_format,
    wants_brief_direct_answer,
)
from app.services.chat.event_news_interpretation import interpret_event_news

if TYPE_CHECKING:
    from app.services.chat.deep_advisor import AdvisorContext

logger = get_logger(__name__)

_INAPP_CHAT_TEMPERATURE = 0.55
_INAPP_CHAT_MAX_TOKENS = 6144


def _forecast_model_block(ctx: "AdvisorContext") -> list[str]:
    from app.services.chat.deep_advisor import _magnitude_label

    output = ctx.output
    interval = output.interval_forecast
    dist = output.distribution_forecast
    lines: list[str] = [
        f"Направление модели: {_magnitude_label(output)}; calibrated_confidence "
        f"{output.calibrated_confidence:.0%}.",
        f"Интервал ~{interval.horizon_days}д: P10 {interval.p10:+.1%}, P90 {interval.p90:+.1%}, "
        f"σ {interval.rolling_volatility:.1%}.",
    ]
    if dist.p50:
        lines.append(
            f"Распределение доходности: P25 {dist.p25:+.1%}, P50 {dist.p50:+.1%}, "
            f"P75 {dist.p75:+.1%}, P95 {dist.p95:+.1%}."
        )
    pf = output.point_forecast
    if pf.plain_language_summary.strip():
        lines.append(f"Point forecast narrative: {pf.plain_language_summary.strip()}")
    if pf.momentum_score is not None:
        lines.append(f"momentum_score: {float(pf.momentum_score):+.2f}")

    action = output.action_forecast
    if action and action.reason:
        lines.append(
            f"Action layer (контекст, не рекомендация): {action.recommendation.value} — "
            f"{action.reason[:240]}"
        )

    if output.sector_regime:
        sr = output.sector_regime
        lines.append(
            f"Sector regime {sr.sector}: {sr.regime.dominant_regime.replace('_', ' ')}, "
            f"sector_momentum {sr.sector_momentum:+.2f}."
        )
    if output.global_regime:
        gr = output.global_regime
        dist_top = sorted(gr.distribution.items(), key=lambda x: -x[1])[:3]
        dist_text = ", ".join(f"{k.replace('_', ' ')} {v:.0%}" for k, v in dist_top)
        lines.append(
            f"Global regime: {gr.dominant_regime.replace('_', ' ')} "
            f"(conf {gr.confidence:.0%}); mix: {dist_text}."
        )

    scenarios = output.scenario_forecast.scenarios if output.scenario_forecast else ()
    for s in sorted(scenarios, key=lambda x: -x.probability)[:4]:
        if s.probability < 0.06:
            continue
        label = s.label_ru or s.name
        narrative = f" — {s.impact_narrative_ru}" if s.impact_narrative_ru else ""
        lines.append(f"Scenario «{label}» p={s.probability:.0%}{narrative}")

    risk_layer = output.risk_forecast
    if risk_layer.plain_language_summary.strip():
        lines.append(f"Risk narrative: {risk_layer.plain_language_summary.strip()[:400]}")

    return lines


def _ticker_analysis_block(ctx: "AdvisorContext", *, include_ml_score: bool = True) -> str:
    payload = ctx.payload
    output = ctx.output
    interval = output.interval_forecast
    lines = [
        f"Тикер: {payload.ticker}, as_of: {payload.as_of or output.as_of}",
        f"Прогноз модели (~{interval.horizon_days}д): P10…P90 {interval.p10:+.1%}…{interval.p90:+.1%}, "
        f"vol {interval.rolling_volatility:.1%}.",
    ]
    lines.extend(_forecast_model_block(ctx))
    if payload.ml_score is not None and include_ml_score:
        lines.append(f"ml_score (контекст, не в начале ответа): {payload.ml_score:.0%}")
    if payload.shap_top_factors:
        lines.append(f"SHAP (контекст): {format_shap_plain_ru(payload.shap_top_factors)}")
    factor_line = format_factor_exposure_user_ru(payload.factor_exposures)
    if factor_line:
        lines.append(f"Факторы: {factor_line}")
    risk_line = format_risk_with_context(payload.risk_metrics)
    if risk_line:
        lines.append(f"Риск: {risk_line}")
    scenario_line = format_scenario_with_shock(payload.scenario_results)
    if scenario_line and "не рассчитаны" not in scenario_line:
        lines.append(f"Сценарии (stress): {scenario_line}")
    conflicts = detect_score_conflicts(payload)
    if conflicts:
        lines.append(f"Напряжения: {conflicts[0]}")
    if payload.peer_comparison:
        peer = payload.peer_comparison
        sector = peer.get("sector")
        avg = peer.get("sector_avg_score")
        if sector and avg is not None:
            lines.append(f"Peer: sector={sector}, sector_avg_score={float(avg):.0%}")
    if payload.news_sentiment_avg is not None:
        lines.append(
            f"News sentiment: +{payload.news_sentiment_positive}/"
            f"-{payload.news_sentiment_negative}/={payload.news_sentiment_neutral}, "
            f"avg {payload.news_sentiment_avg:+.2f}"
        )
    if ctx.fundamentals:
        fund_bits = []
        for key in ("market_cap", "pe_ratio", "dividend_yield", "beta", "eps"):
            val = ctx.fundamentals.get(key)
            if val is not None:
                fund_bits.append(f"{key}={val}")
        if fund_bits:
            lines.append("Fundamentals: " + ", ".join(fund_bits))
    if ctx.quote.get("price") is not None:
        lines.append(
            f"Quote: price={ctx.quote.get('price')}, change_pct={ctx.quote.get('change_pct')}"
        )
    if ctx.analysis.event_risk:
        er = ctx.analysis.event_risk
        lines.append(
            f"Event risk layer: score {er.score:.0%}, news_impact_p {er.news_impact_probability:.0%}, "
            f"articles {er.article_count}."
        )
        if er.reason:
            lines.append(f"Event risk note: {er.reason[:280]}")
    if payload.data_gaps:
        lines.append("Data gaps: " + "; ".join(payload.data_gaps[:6]))
    if ctx.structured_bullets:
        lines.append("Platform summary bullets: " + "; ".join(ctx.structured_bullets[:5]))
    return "\n".join(lines)


def _build_rag_context(question: str, ctx: "AdvisorContext") -> str:
    sym = ctx.payload.ticker
    titles = ctx.payload.news_titles
    corp, ext, _other = _bucket_headlines_for_display(
        titles,
        cap=NEWS_HEADLINE_CAP,
        ticker=sym,
    )
    relevant = tuple(corp + ext)
    matched = headlines_matching_question(question, relevant)
    event_like = is_event_question(question) or is_corporate_geo_question(question)
    if not matched and not event_like:
        matched = headlines_matching_question(question, titles)

    interpretation = interpret_event_news(
        question=question,
        headlines=titles,
        ticker=sym,
    )
    include_ml = interpretation is None
    brief = wants_brief_direct_answer(question)
    structured = use_structured_analyst_format(question)
    mode_label = (
        "brief direct (user requested no full template)"
        if brief
        else ("structured [1]…[7]" if structured else "direct prose (default)")
    )
    lines = [
        f"КРИТИЧНО: ответ строго по инструменту {sym}. "
        "Не используй факты, цифры или новости других тикеров.",
        f"Тикер: {sym}",
        f"Вопрос пользователя: {question.strip()}",
        f"Подсказка типа вопроса: {senior_analyst_intent_hint(question)}",
        f"Режим ответа: {mode_label}",
        "",
        "ticker_analysis:",
        _ticker_analysis_block(ctx, include_ml_score=include_ml and not brief),
    ]
    if matched:
        lines.append("")
        lines.append("Тематически совпадающие заголовки (entity_relevance + question match):")
        for title in matched[:8]:
            lines.append(f"- {title}")
    elif event_like:
        lines.append("")
        lines.append(
            "Тематически совпадающих заголовков нет. Запрещено цитировать прочие новости "
            "по тикеру как «ключевой материал» для этого вопроса; ответ строй на ticker_analysis. "
            "Если добавляешь общий корпоративный контекст, отдели его блоком "
            "«Внешний контекст (не из ленты Quant Analytics)»."
        )
    elif relevant:
        lines.append("")
        lines.append("Корпоративные/рыночные заголовки:")
        for title in relevant[:8]:
            lines.append(f"- {title}")
    else:
        lines.append("")
        lines.append("Релевантных заголовков в снимке нет.")

    if ctx.macro_snippet:
        lines.append("")
        lines.append(f"Макро-снимок: {ctx.macro_snippet[:800]}")
    if ctx.scenario_snippet:
        lines.append("")
        lines.append(f"Scenario snippet: {ctx.scenario_snippet[:600]}")

    if interpretation:
        lines.append("")
        lines.append("Подсказки интерпретации события:")
        lines.append(interpretation.llm_hints_block())

    if is_event_question(question):
        lines.append("")
        lines.append(EVENT_QUESTION_RUBRIC_RU)

    return "\n".join(lines)


async def try_llm_senior_analyst_answer(question: str, ctx: "AdvisorContext") -> str | None:
    """Call configured LLM for any ticker chat question; None if disabled or failed."""
    from app.services.llm.llm_service import LLMService, llm_enabled

    if not llm_enabled():
        return None

    brief = wants_brief_direct_answer(question)
    structured = use_structured_analyst_format(question)
    rag = _build_rag_context(question, ctx)
    system = build_senior_analyst_llm_system(structured=structured, brief=brief)
    user_prompt = senior_analyst_user_prompt(structured=structured, brief=brief)
    max_tokens = 1200 if brief else _INAPP_CHAT_MAX_TOKENS
    try:
        from app.core.config import settings

        timeout = max(5.0, float(settings.LLM_TIMEOUT_SECONDS))
        content = await asyncio.wait_for(
            LLMService.complete(
                "inapp_chat",
                user_prompt,
                system=system,
                context=f"Контекст анализа:\n{rag}",
                temperature=_INAPP_CHAT_TEMPERATURE,
                max_tokens=max_tokens,
            ),
            timeout=timeout,
        )
        if content:
            logger.info(
                "Senior analyst LLM reply",
                symbol=ctx.payload.ticker,
                llm_called=True,
                context_chars=len(rag),
                raw_llm_len=len(content),
            )
        return content or None
    except asyncio.TimeoutError:
        logger.warning(
            "Advisor LLM reply timed out",
            timeout_seconds=timeout,
            symbol=ctx.payload.ticker,
        )
        return None
    except Exception as exc:
        logger.warning(
            "Advisor LLM reply failed",
            error=str(exc),
            symbol=ctx.payload.ticker,
        )
        return None


async def try_llm_event_answer(question: str, ctx: "AdvisorContext") -> str | None:
    """Backward-compatible alias — all questions use senior analyst path."""
    return await try_llm_senior_analyst_answer(question, ctx)
