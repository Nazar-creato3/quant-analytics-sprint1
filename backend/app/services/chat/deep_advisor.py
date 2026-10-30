"""Deep ticker advisor — payload-grounded ticker chat (Section 7.1, no external LLM)."""
from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from enum import Flag, auto
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.analysis.context import AnalysisContext, gather_analysis_context
from app.services.analysis.ticker_payload import (
    TickerAnalysisPayload,
    assemble_ticker_analysis_payload,
)
from app.services.chat.advisor_prompt import (
    DISCLOSURE_RU,
    NEWS_HEADLINE_CAP,
    _DATA_MISSING_RU,
    _bucket_headlines_for_display,
    detect_score_conflicts,
    disclosure_needed,
    format_factor_exposure_user_ru,
    format_news_from_payload,
    format_risk_with_context,
    format_scenario_with_shock,
    format_senior_analyst_sections,
    format_shap_plain_ru,
    has_repeated_substring,
    headlines_matching_question,
    is_corporate_geo_question,
    is_event_question,
    is_investment_program_question,
    is_logistics_supply_question,
    is_simple_question,
    log_shap_factor_mentions,
    mentions_shap,
    synthesize_event_answer,
    wants_brief_direct_answer,
    wants_full_breakdown,
    use_structured_analyst_format,
    _SIZING_QUESTION,
)

# The user sees only the answer: no model, vendor or pipeline names (audit rule: no technical info in UI).
CHAT_SOURCE_LLM_RU = ""
CHAT_SOURCE_RULE_RU = ""
from app.services.prediction_hierarchy.orchestrator import get_hierarchy_orchestrator
from app.services.prediction_hierarchy.types import ForecastOutput

logger = get_logger(__name__)


def _show_chat_source_footer() -> bool:
    from app.core.config import settings

    return bool(settings.CHAT_DEBUG_FOOTERS or not settings.LLM_ENABLED)


def _show_llm_disclosure() -> bool:
    from app.core.config import settings

    return bool(settings.CHAT_SHOW_DISCLOSURE)

_TIMEFRAME_DAYS: dict[str, int] = {
    "день": 1,
    "дня": 1,
    "недел": 7,
    "week": 7,
    "месяц": 30,
    "month": 30,
    "квартал": 90,
    "quarter": 90,
    "год": 365,
    "year": 365,
}

_INTENT_PRIORITY: tuple[str, ...] = (
    "MARKET_DATA",
    "BUY",
    "SELL",
    "RISK",
    "FORECAST",
    "TIMEFRAME",
    "NEWS",
    "REGULATORY",
    "MACRO",
    "POLITICS",
    "GENERAL",
)

_MAGNITUDE_RU: dict[str, str] = {
    "strong_up": "сильный рост",
    "up": "умеренный рост",
    "neutral": "боковик",
    "down": "умеренное снижение",
    "strong_down": "сильное снижение",
}

_REGULATORY_NEWS = re.compile(
    r"регулятор|regulatory|лиценз|compliance|антимонопол|antitrust|"
    r"sec\b|цб\s*рф|центробанк|закон|штраф|расследован|audit|аудит|"
    r"санкц|sanction|embargo|экспортн|импортн",
    re.IGNORECASE,
)
_POLITICS_NEWS = re.compile(
    r"полит|геопол|выбор|войн|конфликт|trade\s+war|tariff|тариф|"
    r"дипломат|nato|нato|кремл|белый\s+дом|white\s+house",
    re.IGNORECASE,
)
_FINANCIAL_NEWS = re.compile(
    r"earnings|выручк|прибыл|убыт|дивиденд|guidance|отчёт|отчет|"
    r"revenue|profit|loss|ipo|merger|слияни|поглощ",
    re.IGNORECASE,
)


class QuestionIntent(Flag):
    MARKET_DATA = auto()
    BUY = auto()
    SELL = auto()
    RISK = auto()
    FORECAST = auto()
    NEWS = auto()
    MACRO = auto()
    POLITICS = auto()
    REGULATORY = auto()
    TIMEFRAME = auto()
    GENERAL = auto()


@dataclass(slots=True)
class AdvisorContext:
    output: ForecastOutput
    analysis: AnalysisContext
    payload: TickerAnalysisPayload
    news_headlines: list[str] = field(default_factory=list)
    macro_snippet: str = ""
    scenario_snippet: str = ""
    structured_bullets: list[str] = field(default_factory=list)
    fundamentals: dict[str, Any] = field(default_factory=dict)
    quote: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvidenceSection:
    title: str
    items: tuple[str, ...]


def parse_market_data_subtype(question: str) -> str | None:
    """Detect which market-data metric the user asked about."""
    lowered = question.lower()
    if any(w in lowered for w in ("капитализац", "market cap", "capitalization", "рыночная стоимость")):
        return "market_cap"
    if any(w in lowered for w in ("p/e", "pe ratio", "p/e ratio", "мультипликатор", "оценк")):
        return "pe_ratio"
    if any(w in lowered for w in ("дивиденд", "dividend")):
        return "dividend_yield"
    if any(w in lowered for w in ("цена", "котировк", "price", "стоимость акци", "сколько стоит")):
        return "price"
    if any(w in lowered for w in ("объём", "объем", "volume", "ликвидност")):
        return "volume"
    if any(w in lowered for w in ("beta", "бета")):
        return "beta"
    if any(w in lowered for w in ("eps", "прибыль на акцию", "earnings per share")):
        return "eps"
    if any(w in lowered for w in ("roe", "рентабельность капитала")):
        return "roe"
    return None


def parse_question_intent(question: str) -> QuestionIntent:
    lowered = question.lower()
    intent = QuestionIntent(0)

    if parse_market_data_subtype(question) or any(
        w in lowered
        for w in ("фундамент", "fundamental", "баланс", "выручк", "revenue", "прибыл")
    ):
        intent |= QuestionIntent.MARKET_DATA
    if any(w in lowered for w in ("куп", "buy", "войти", "long", "набра", "добав")):
        intent |= QuestionIntent.BUY
    if any(w in lowered for w in ("прод", "sell", "шорт", "short", "выйти", "закры", "сброс")):
        intent |= QuestionIntent.SELL
    if any(w in lowered for w in ("риск", "risk", "опас", "волат", "просад")):
        intent |= QuestionIntent.RISK
    if any(w in lowered for w in ("прогноз", "forecast", "куда", "цена", "target", "ожид")):
        intent |= QuestionIntent.FORECAST
    if any(w in lowered for w in ("новост", "news", "событ", "earnings", "отчёт", "отчет")):
        intent |= QuestionIntent.NEWS
    if any(w in lowered for w in ("макро", "macro", "ставк", "инфля", "fed", "цб", "эконом")):
        intent |= QuestionIntent.MACRO
    if any(w in lowered for w in ("полит", "геопол", "санкц", "выбор", "войн", "конфликт")):
        intent |= QuestionIntent.POLITICS
    if any(w in lowered for w in ("регулятор", "regulatory", "юридич", "legal", "compliance", "лиценз", "закон")):
        intent |= QuestionIntent.REGULATORY
    if any(w in lowered for w in tuple(_TIMEFRAME_DAYS.keys())):
        intent |= QuestionIntent.TIMEFRAME

    if intent == QuestionIntent(0):
        intent = QuestionIntent.GENERAL
    return intent


def primary_intent(intent: QuestionIntent, question: str = "") -> QuestionIntent:
    """Pick the dominant intent when several flags are set."""
    if question and is_corporate_geo_question(question):
        return QuestionIntent.GENERAL
    if question and is_event_question(question):
        if intent & QuestionIntent.REGULATORY:
            return QuestionIntent.REGULATORY
        if intent & QuestionIntent.NEWS:
            return QuestionIntent.NEWS
        if intent & (QuestionIntent.POLITICS | QuestionIntent.MACRO):
            return QuestionIntent.NEWS
    for name in _INTENT_PRIORITY:
        flag = QuestionIntent[name]
        if intent & flag:
            return flag
    return QuestionIntent.GENERAL


def _question_hash(question: str) -> int:
    return int(hashlib.md5(question.strip().lower().encode()).hexdigest()[:8], 16)


def _normalize_for_dedup(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def dedupe_repeated_substrings(text: str, *, min_len: int = 50) -> str:
    """Drop duplicate paragraphs and repeated long substrings (LLM echo guard)."""
    if not text:
        return text
    blocks = text.split("\n\n")
    unique_blocks: list[str] = []
    seen_block: set[str] = set()
    for block in blocks:
        key = _normalize_for_dedup(block)
        if len(key) >= min_len and key in seen_block:
            continue
        if len(key) >= min_len:
            seen_block.add(key)
        unique_blocks.append(block)
    result = "\n\n".join(unique_blocks).strip()
    while has_repeated_substring(result, min_len=min_len):
        compact = re.sub(r"\s+", " ", result.strip())
        removed = False
        for length in range(min(len(compact) // 2, 400), min_len - 1, -1):
            for i in range(len(compact) - length + 1):
                chunk = compact[i : i + length]
                if len(chunk.strip()) < min_len:
                    continue
                j = compact.find(chunk, i + length)
                if j != -1:
                    result = (compact[:j] + compact[j + length :]).strip()
                    removed = True
                    break
            if removed:
                break
        if not removed:
            break
    return result


def finalize_advisor_reply(text: str) -> str:
    cleaned = dedupe_repeated_substrings(text.strip())
    return _strip_internal_verdict_patterns(cleaned)


_RAW_VERDICT_RE = re.compile(
    r"(?:Positive|Neutral|Negative)\s*\|\s*horizon\s*~?\s*\d+\s*d\s*\|\s*confidence\s*\d+%",
    re.IGNORECASE,
)
# Health check `chat_no_raw_debug` — any "confidence NN% … horizon" substring.
_DEBUG_LEAK_RE = re.compile(r"confidence\s*\d+%.*horizon", re.IGNORECASE | re.DOTALL)


def _strip_internal_verdict_patterns(text: str) -> str:
    """Remove leaked internal verdict tokens from user-facing chat replies."""
    if not text:
        return text
    cleaned = text
    if _RAW_VERDICT_RE.search(cleaned):
        lines = []
        for line in cleaned.splitlines():
            if _RAW_VERDICT_RE.search(line):
                continue
            lines.append(line)
        cleaned = "\n".join(lines)
    if _DEBUG_LEAK_RE.search(cleaned):
        cleaned = _DEBUG_LEAK_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


_TONE_RU: dict[str, str] = {
    "Positive": "умеренно позитивный",
    "Neutral": "нейтральный",
    "Negative": "осторожно негативный",
}


def _confidence_label_ru(conf: float) -> str:
    if conf < 0.45:
        return "низкой"
    if conf < 0.70:
        return "умеренной"
    return "высокой"


def _was_shown(text: str, prior_messages: tuple[str, ...], *, min_len: int = 24) -> bool:
    if not text or not prior_messages:
        return False
    needle = _normalize_for_dedup(text)
    if len(needle) < min_len:
        return False
    for prior in prior_messages:
        haystack = _normalize_for_dedup(prior)
        if needle in haystack:
            return True
    return False


def _extract_horizon_days(question: str) -> int | None:
    lowered = question.lower()
    for token, days in _TIMEFRAME_DAYS.items():
        if token in lowered:
            return days
    match = re.search(r"(\d+)\s*(дн|day|нед|week|мес|month)", lowered)
    if match:
        n = int(match.group(1))
        unit = match.group(2)
        if "нед" in unit or "week" in unit:
            return n * 7
        if "мес" in unit or "month" in unit:
            return n * 30
        return n
    return None


def _format_large_number(value: float, *, currency: str = "") -> str:
    suffix = f" {currency}".rstrip()
    abs_val = abs(value)
    if abs_val >= 1e12:
        return f"{value / 1e12:.2f} трлн{suffix}"
    if abs_val >= 1e9:
        return f"{value / 1e9:.2f} млрд{suffix}"
    if abs_val >= 1e6:
        return f"{value / 1e6:.2f} млн{suffix}"
    return f"{value:,.0f}{suffix}"


def _format_pct(value: float) -> str:
    if abs(value) <= 1.0:
        return f"{value:.1%}"
    return f"{value:.2f}%"


def _magnitude_label(output: ForecastOutput) -> str:
    mc = output.point_forecast.magnitude_class.value
    return _MAGNITUDE_RU.get(mc, mc.replace("_", " "))


def _categorize_headlines(headlines: list[str]) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {"regulatory": [], "politics": [], "financial": [], "general": []}
    for headline in headlines:
        if _REGULATORY_NEWS.search(headline):
            buckets["regulatory"].append(headline)
        elif _POLITICS_NEWS.search(headline):
            buckets["politics"].append(headline)
        elif _FINANCIAL_NEWS.search(headline):
            buckets["financial"].append(headline)
        else:
            buckets["general"].append(headline)
    return buckets


async def _load_structured_bullets(db: AsyncSession, instrument_id: int, symbol: str) -> list[str]:
    try:
        from app.services.forecast.daily_builder import get_daily_forecast_builder

        builder = get_daily_forecast_builder()
        payload = await builder.build(db, instrument_id=instrument_id, symbol=symbol)
        bullets: list[str] = []
        for item in payload.get("actionable_summary") or []:
            if isinstance(item, str) and item.strip():
                bullets.append(item.strip())
        for item in (payload.get("sector_opportunities") or [])[:2]:
            if isinstance(item, dict):
                title = item.get("title") or item.get("text")
                if title:
                    bullets.append(str(title).strip())
        return bullets[:5]
    except Exception as exc:
        logger.debug("Advisor structured load failed", symbol=symbol, error=str(exc))
        return []


async def _load_fundamentals(symbol: str) -> dict[str, Any]:
    try:
        from app.services.market_data.enrichment import fetch_fundamentals

        return await fetch_fundamentals(symbol)
    except Exception as exc:
        logger.debug("Advisor fundamentals load failed", symbol=symbol, error=str(exc))
        return {}


async def _load_quote(symbol: str) -> dict[str, Any]:
    try:
        from app.services.market_data.client import get_latest_quote_resolved

        return await get_latest_quote_resolved(symbol)
    except Exception as exc:
        logger.debug("Advisor quote load failed", symbol=symbol, error=str(exc))
        return {}


def _scenario_snippet(output: ForecastOutput) -> str:
    scenarios = output.scenario_forecast.scenarios if output.scenario_forecast else ()
    if not scenarios:
        return ""
    top = sorted(scenarios, key=lambda s: s.probability, reverse=True)[:3]
    parts: list[str] = []
    for s in top:
        if s.probability <= 0.05:
            continue
        label = s.label_ru or s.name
        detail = f" — {s.impact_narrative_ru}" if s.impact_narrative_ru else ""
        parts.append(f"{label} ({s.probability:.0%}){detail}")
    if not parts:
        return ""
    return "Сценарии модели: " + "; ".join(parts) + "."


def politics_intent_requested(intent: QuestionIntent) -> bool:
    return bool(
        intent
        & (
            QuestionIntent.MACRO
            | QuestionIntent.POLITICS
            | QuestionIntent.REGULATORY
            | QuestionIntent.NEWS
        )
    )


async def gather_advisor_context(
    db: AsyncSession,
    *,
    instrument_id: int,
    symbol: str,
    output: ForecastOutput | None = None,
    include_politics: bool = False,
) -> AdvisorContext:
    if output is None:
        orchestrator = get_hierarchy_orchestrator()
        output = await orchestrator.get_forecast(
            db,
            instrument_id,
            symbol=symbol,
            include_narrative=True,
            use_cache=True,
        )

    analysis_task = asyncio.create_task(
        gather_analysis_context(
            db,
            instrument_id=instrument_id,
            symbol=symbol,
            output=output,
            include_structured=False,
            include_politics=include_politics,
        )
    )
    structured_task = asyncio.create_task(_load_structured_bullets(db, instrument_id, symbol))
    fundamentals_task = asyncio.create_task(_load_fundamentals(symbol))
    quote_task = asyncio.create_task(_load_quote(symbol))

    analysis, structured, fundamentals, quote = await asyncio.gather(
        analysis_task,
        structured_task,
        fundamentals_task,
        quote_task,
    )
    if structured:
        analysis.structured_bullets = structured

    payload = assemble_ticker_analysis_payload(
        output=output,
        analysis=analysis,
        fundamentals=fundamentals,
    )

    return AdvisorContext(
        output=output,
        analysis=analysis,
        payload=payload,
        news_headlines=[h.title for h in analysis.news_headlines],
        macro_snippet=analysis.macro_snippet,
        scenario_snippet=_scenario_snippet(output),
        structured_bullets=analysis.structured_bullets,
        fundamentals=fundamentals,
        quote=quote,
    )


def _market_data_direct_answer(
    question: str,
    ctx: AdvisorContext,
) -> str:
    """Answer market-data questions directly; never substitute risk advice."""
    sym = ctx.output.symbol
    subtype = parse_market_data_subtype(question)
    fund = ctx.fundamentals
    quote = ctx.quote

    if subtype == "market_cap":
        cap = fund.get("market_cap")
        if cap is not None:
            currency = "RUB" if fund.get("exchange") == "MOEX" else "USD"
            source = fund.get("source", "yfinance")
            source_label = {
                "moex_iss": "MOEX ISS",
                "fmp": "Financial Modeling Prep",
                "yfinance": "yfinance" + (" .ME" if fund.get("exchange") == "MOEX" else ""),
            }.get(source, source)
            return (
                f"Рыночная капитализация {sym}: {_format_large_number(float(cap), currency=currency)} "
                f"(источник: {source_label})."
            )
        note = fund.get("note", "")
        extra = f" {note}" if note else ""
        return (
            f"Данные о капитализации {sym} сейчас недоступны в подключённых источниках.{extra} "
            "Для MOEX-акций попробуйте позже или проверьте котировку на moex.com."
        )

    if subtype == "pe_ratio":
        pe = fund.get("pe_ratio")
        if pe is not None:
            return f"P/E (trailing/forward) по {sym}: {float(pe):.2f}."
        return f"Данные о P/E для {sym} недоступны — подключённые источники не вернули мультипликатор."

    if subtype == "dividend_yield":
        div = fund.get("dividend_yield")
        history = fund.get("dividend_history") or []
        if div is not None:
            answer = f"Дивидендная доходность {sym} (trailing 12м, MOEX ISS): {_format_pct(float(div))}."
            if history:
                latest = history[0]
                answer += (
                    f" Последняя выплата: {latest.get('value')} {latest.get('currency', 'RUB')} "
                    f"(дата реестра {latest.get('registry_close_date')})."
                )
            return answer
        if history:
            latest = history[0]
            return (
                f"По {sym} в MOEX ISS есть история выплат, но текущая цена недоступна — "
                f"доходность не рассчитана. Последняя выплата: {latest.get('value')} "
                f"{latest.get('currency', 'RUB')} (дата реестра {latest.get('registry_close_date')})."
            )
        return (
            f"Данные о дивидендной доходности {sym} недоступны в подключённых источниках "
            "(MOEX ISS / yfinance). Уточните тикер или повторите запрос позже."
        )

    if subtype == "price":
        price = quote.get("price")
        if price is not None:
            change = quote.get("change_pct")
            change_text = f", изменение {float(change):+.2f}%" if change is not None else ""
            return f"Текущая цена {sym}: {float(price):.2f}{change_text}."
        return f"Актуальная котировка {sym} сейчас недоступна."

    if subtype == "volume":
        vol = quote.get("volume") or fund.get("averageVolume")
        if vol is not None:
            return f"Объём торгов {sym}: {_format_large_number(float(vol))}."
        return f"Данные об объёме торгов {sym} недоступны."

    if subtype == "beta":
        beta = fund.get("beta")
        if beta is not None:
            return f"Бета {sym}: {float(beta):.2f} (чувствительность к рынку)."
        return f"Данные о бете {sym} недоступны."

    if subtype == "eps":
        eps = fund.get("eps")
        if eps is not None:
            return f"EPS (прибыль на акцию) {sym}: {float(eps):.2f}."
        return f"Данные об EPS для {sym} недоступны."

    if subtype == "roe":
        roe = fund.get("roe")
        if roe is not None:
            return f"ROE {sym}: {_format_pct(float(roe))}."
        return f"Данные о ROE для {sym} недоступны."

    parts: list[str] = []
    cap = fund.get("market_cap")
    if cap is not None:
        parts.append(f"капитализация {_format_large_number(float(cap))}")
    price = quote.get("price")
    if price is not None:
        parts.append(f"цена {float(price):.2f}")
    pe = fund.get("pe_ratio")
    if pe is not None:
        parts.append(f"P/E {float(pe):.2f}")
    if parts:
        return f"Фундаментальные показатели {sym}: " + ", ".join(parts) + "."
    return (
        f"Фундаментальные данные по {sym} ограничены — "
        "подключённые источники не вернули метрики. Уточните конкретный показатель "
        "(капитализация, P/E, дивиденды, цена)."
    )


def _payload_score_line(payload: TickerAnalysisPayload) -> str:
    if payload.ml_score is None:
        return _DATA_MISSING_RU
    return f"ml_score модели: {payload.ml_score:.0%}."


def _metrics_context_lines(ctx: AdvisorContext) -> str:
    """Model-only metrics for sections 3–5 — risk is appended separately."""
    payload = ctx.payload
    parts: list[str] = []
    if payload.ml_score is not None:
        parts.append(_payload_score_line(payload))
    if payload.shap_top_factors:
        parts.append(format_shap_plain_ru(payload.shap_top_factors))
    return " ".join(parts)


def _structured_verdict_line(ctx: AdvisorContext, *, tone: str = "Neutral") -> str:
    """Natural-language verdict for section [7] — never raw internal tokens."""
    interval = ctx.output.interval_forecast
    conf = ctx.output.calibrated_confidence
    tone_ru = _TONE_RU.get(tone, "нейтральный")
    conf_ru = _confidence_label_ru(conf)
    return (
        f"Итог по модели на горизонте около {interval.horizon_days} дней: {tone_ru} bias "
        f"с {conf_ru} уверенностью (~{conf:.0%}). "
        "Это аналитическая справка по данным Quant Analytics, а не инвестиционная рекомендация."
    )


def _refine_repeat_answer(
    answer: str,
    question: str,
    ctx: AdvisorContext,
    *,
    prior_messages: tuple[str, ...],
) -> str:
    """Follow-up on similar wording — add a new angle instead of a generic suffix."""
    if not _was_shown(answer, prior_messages, min_len=16):
        return answer
    extras: list[str] = []
    matched = headlines_matching_question(question, ctx.payload.news_titles)
    if matched:
        extras.append(f"Дополнительный угол: «{matched[0]}».")
    interval = ctx.output.interval_forecast
    extras.append(
        f"Горизонт ~{interval.horizon_days}д: интервал {interval.p10:+.1%}…{interval.p90:+.1%}."
    )
    if is_logistics_supply_question(question):
        extras.append("Supply chain: Taiwan/lead time и margin guidance — ключевые триггеры.")
    return f"{answer} {' '.join(extras[:2])}"


def _structured_lead(
    question: str,
    intent: QuestionIntent,
    ctx: AdvisorContext,
    *,
    prior_messages: tuple[str, ...] = (),
) -> str:
    """Section [1] — question-specific lead without ml_score/SHAP template opener."""
    output = ctx.output
    payload = ctx.payload
    sym = output.symbol
    lead = primary_intent(intent, question)

    if is_logistics_supply_question(question):
        matched = headlines_matching_question(question, payload.news_titles)
        topic = "Taiwan/логистика и цепочка поставок"
        if matched:
            answer = (
                f"По {topic} для {sym}: в данных «{matched[0]}» — оценивайте lead time, "
                f"маржу и guidance, а не только движение у 52-week high."
            )
        else:
            answer = (
                f"По {topic} для {sym}: в текущем снимке нет детализированной логистической "
                f"разбивки — явный data gap по Taiwan/supply; вывод только из доступных новостей и модели."
            )
        return _refine_repeat_answer(answer, question, ctx, prior_messages=prior_messages)

    if is_corporate_geo_question(question):
        interval = output.interval_forecast
        mag = _magnitude_label(output)
        matched = headlines_matching_question(question, payload.news_titles)
        news_clause = (
            f"В ленте есть тематическое подтверждение: «{matched[0]}». "
            if matched
            else f"В текущей ленте нет заголовка, совпадающего с темой HQ/географии; случайные новости по {sym} не являются подтверждением. "
        )
        answer = (
            f"Для {sym} перенос штаб-квартиры сам по себе обычно нейтрален для стоимости акций, "
            f"если не меняет налоги, затраты, доступ к талантам или управленческое исполнение. "
            f"{news_clause}По модели Quant Analytics на ~{interval.horizon_days}д: «{mag}», "
            f"интервал {interval.p10:+.1%}…{interval.p90:+.1%}; поэтому вывод должен идти от "
            f"прогноза/риска, а не от нерелевантной ленты."
        )
        return _refine_repeat_answer(answer, question, ctx, prior_messages=prior_messages)

    if is_investment_program_question(question):
        matched = headlines_matching_question(question, payload.news_titles)
        capex_ref = "515 млрд" if "515" in question else "инвестпрограмму/CAPEX"
        if matched:
            answer = (
                f"Сокращение {capex_ref} по {sym}: «{matched[0]}» — давление на FCF и дивиденды, "
                f"но возможное улучшение дисциплины капзатрат."
            )
        else:
            answer = (
                f"По изменению {capex_ref} для {sym}: в ленте нет прямого заголовка — "
                f"используйте формулировку вопроса; следите за FCF и guidance."
            )
        return _refine_repeat_answer(answer, question, ctx, prior_messages=prior_messages)

    if lead == QuestionIntent.MARKET_DATA:
        answer = _market_data_direct_answer(question, ctx)

    elif lead in (QuestionIntent.BUY, QuestionIntent.SELL):
        interval = output.interval_forecast
        mag = _magnitude_label(output)
        horizon = _extract_horizon_days(question) or interval.horizon_days
        side = "покупке" if lead == QuestionIntent.BUY else "продаже"
        answer = (
            f"По {side} {sym} на ~{horizon}д: без прямой рекомендации buy/sell — модель видит "
            f"«{mag}» (интервал {interval.p10:+.1%}…{interval.p90:+.1%}); "
            f"размер позиции через сценарии и лимиты по риску."
        )
        if _SIZING_QUESTION.search(question):
            answer += " Указанная в вопросе сумма должна быть совместима с хвостовым риском бумаги."

    elif lead == QuestionIntent.RISK:
        answer = format_risk_with_context(payload.risk_metrics)
        conflicts = detect_score_conflicts(payload)
        if conflicts:
            answer += " " + conflicts[0]

    elif lead in (QuestionIntent.FORECAST, QuestionIntent.TIMEFRAME):
        interval = output.interval_forecast
        mag = _magnitude_label(output)
        horizon = _extract_horizon_days(question) or interval.horizon_days
        answer = (
            f"На горизонте ~{horizon}д по {sym}: направление — {mag}. "
            f"Интервал P10…P90: {interval.p10:+.1%}…{interval.p90:+.1%}; "
            f"волатильность {interval.rolling_volatility:.1%}."
        )

    elif lead == QuestionIntent.NEWS:
        matched = headlines_matching_question(question, payload.news_titles)
        if matched:
            answer = f"Главный материал по запросу: «{matched[0]}»."
        else:
            answer = format_news_from_payload(
                payload.news_titles,
                positive=payload.news_sentiment_positive,
                negative=payload.news_sentiment_negative,
                neutral=payload.news_sentiment_neutral,
                avg_score=payload.news_sentiment_avg,
                ticker=payload.ticker,
            )[:400]

    elif lead == QuestionIntent.REGULATORY:
        reg_news = tuple(h for h in payload.news_titles if _REGULATORY_NEWS.search(h))
        if reg_news:
            answer = f"Регуляторный фокус: «{reg_news[0]}»."
        else:
            answer = f"Регуляторных заголовков по {sym} в текущих данных анализа нет."

    elif lead in (QuestionIntent.MACRO, QuestionIntent.POLITICS):
        regime = output.global_regime.dominant_regime if output.global_regime else "неопределён"
        regime_conf = output.global_regime.confidence if output.global_regime else 0.0
        macro_part = ctx.macro_snippet or "макро-снимок ограничен"
        answer = (
            f"Макро-режим: {regime.replace('_', ' ')} (уверенность {regime_conf:.0%}). "
            f"{macro_part}"
        )

    elif mentions_shap(question):
        answer = (
            f"Драйверы скора по {sym}: "
            f"{format_shap_plain_ru(payload.shap_top_factors) if payload.shap_top_factors else _DATA_MISSING_RU}"
        )
        conflicts = detect_score_conflicts(payload)
        if conflicts:
            answer += " " + conflicts[0]

    elif lead == QuestionIntent.GENERAL:
        interval = output.interval_forecast
        mag = _magnitude_label(output)
        answer = (
            f"Сводка по {sym} по сути вопроса: «{question.strip()[:120]}» — "
            f"модель на ~{interval.horizon_days}д: «{mag}», интервал "
            f"{interval.p10:+.1%}…{interval.p90:+.1%}."
        )

    else:
        interval = output.interval_forecast
        mag = _magnitude_label(output)
        answer = (
            f"Сводка по {sym}: {mag}, интервал {interval.p10:+.1%}…{interval.p90:+.1%}."
        )

    return _refine_repeat_answer(answer, question, ctx, prior_messages=prior_messages)


def _direct_answer(
    question: str,
    intent: QuestionIntent,
    ctx: AdvisorContext,
    *,
    prior_messages: tuple[str, ...] = (),
) -> str:
    """Grounded direct lead — delegates to question-specific structured section [1]."""
    return _structured_lead(question, intent, ctx, prior_messages=prior_messages)


def _build_analyst_section_map(
    *,
    question: str,
    ctx: AdvisorContext,
    prior_messages: tuple[str, ...] = (),
) -> dict[str, str]:
    """Shared section bodies for structured [1]…[7] and direct prose fallbacks."""
    intent = parse_question_intent(question)
    prior_advisor = prior_messages[-3:]
    sym = ctx.output.symbol
    interval = ctx.output.interval_forecast
    mag = _magnitude_label(ctx.output)
    event_focus = is_event_question(question) and not wants_full_breakdown(question)

    if event_focus and not is_corporate_geo_question(question):
        event_lead = _compose_event_reply(
            question=question,
            ctx=ctx,
            prior_messages=prior_advisor,
        )
        section_one = event_lead.split("\n\n")[0].strip()
    else:
        section_one = _structured_lead(
            question, intent, ctx, prior_messages=prior_advisor
        )

    if event_focus and is_corporate_geo_question(question):
        section_two = (
            f"Справочно по модели на ~{interval.horizon_days}д для {sym}: "
            f"интервал {interval.p10:+.1%}…{interval.p90:+.1%}; "
            "это основная численная опора, пока нет тематической HQ-новости в ленте."
        )
    elif event_focus:
        section_two = (
            f"Справочно по модели на ~{interval.horizon_days}д для {sym}: "
            f"интервал {interval.p10:+.1%}…{interval.p90:+.1%} "
            f"(отдельно от новостного relief, без конфликтующего направления модели)."
        )
    else:
        section_two = (
            f"Структура рынка по {sym}: «{mag}» на ~{interval.horizon_days}д, "
            f"интервал {interval.p10:+.1%}…{interval.p90:+.1%}."
        )
        if ctx.macro_snippet:
            section_two += f" {ctx.macro_snippet[:320]}"

    matched = headlines_matching_question(question, ctx.payload.news_titles)
    if matched:
        section_three = "Катализаторы: " + "; ".join(f"«{h}»" for h in matched[:4]) + "."
    elif event_focus:
        section_three = (
            "В новостной ленте нет заголовков, совпадающих с темой вопроса; "
            "не используем прочие новости тикера как катализатор."
        )
    elif ctx.payload.news_titles:
        section_three = format_news_from_payload(
            ctx.payload.news_titles,
            positive=ctx.payload.news_sentiment_positive,
            negative=ctx.payload.news_sentiment_negative,
            neutral=ctx.payload.news_sentiment_neutral,
            avg_score=ctx.payload.news_sentiment_avg,
            ticker=ctx.payload.ticker,
        )[:600]
    else:
        section_three = "В ленте данных нет заголовков — опираемся на модельный снимок."

    scenario_line = format_scenario_with_shock(ctx.payload.scenario_results)
    if event_focus and is_corporate_geo_question(question):
        section_four = (
            "Base: нейтральный фундаментальный эффект без доказанного изменения затрат/налогов. "
            "Bull: перенос снижает costs/tax burden или улучшает hiring. "
            "Bear: disruption, one-off costs или потеря управленческого фокуса."
        )
    elif event_focus:
        section_four = (
            f"Base: relief по событию (краткосрочно). Bull: follow-through сделки; "
            f"Bear: отсутствие закрытия сделки / новый regulatory shock."
        )
    elif scenario_line and "не рассчитаны" not in scenario_line:
        section_four = (
            f"Base: {mag} ({interval.p10:+.1%}…{interval.p90:+.1%}). "
            f"Bull/bear через сценарии: {scenario_line}"
        )
    else:
        section_four = (
            f"Base: {mag}. Bull: верх интервала {interval.p90:+.1%}; "
            f"Bear: низ {interval.p10:+.1%}."
        )

    metrics = _metrics_context_lines(ctx)
    section_five = format_risk_with_context(ctx.payload.risk_metrics)
    conflicts = detect_score_conflicts(ctx.payload)
    if conflicts:
        section_five += " " + conflicts[0]
    if metrics and not event_focus:
        section_five += f" Модель: {metrics}"
    elif event_focus and is_corporate_geo_question(question):
        section_five = (
            "Главный риск ошибки — принять корпоративный нарратив за ценовой драйвер без цифр "
            "по затратам, налогам, hiring или productivity."
        )
    elif event_focus:
        section_five = (
            "Tail/regulatory: следите за follow-through сделки и новостным relief; "
            "метрики модели вторичны относительно события."
        )

    if is_logistics_supply_question(question):
        section_six = (
            "Lead times Taiwan/packaging, backlog, margin guidance, конкуренты (AMD/Intel)."
        )
    elif is_corporate_geo_question(question):
        section_six = (
            "Налоги, компенсации и найм, управленческий фокус, capex на офисы, "
            "official filing/press release по HQ."
        )
    elif is_investment_program_question(question):
        section_six = "CAPEX vs FCF, дивиденды, guidance, реакция на 515 млрд/инвестпрограмму."
    else:
        section_six = "Follow-through новостей, макро (ставки/FX/VIX), исполнение guidance."

    tone = "Neutral"
    if mag in ("сильный рост", "умеренный рост"):
        tone = "Positive"
    elif mag in ("умеренное снижение", "сильное снижение"):
        tone = "Negative"
    section_seven = _structured_verdict_line(ctx, tone=tone)

    if not is_simple_question(question) or wants_full_breakdown(question):
        extra_sections = _build_research_sections(
            intent, ctx, question=question, prior_messages=prior_advisor
        )
        if extra_sections:
            bits = []
            for sec in extra_sections[:3]:
                bits.append(f"{sec.title}: {'; '.join(sec.items[:2])}")
            section_three += " " + " ".join(bits)

    return {
        "1": section_one,
        "2": section_two,
        "3": section_three,
        "4": section_four,
        "5": section_five,
        "6": section_six,
        "7": section_seven,
    }


def compose_structured_analyst_reply(
    *,
    question: str,
    ctx: AdvisorContext,
    prior_messages: tuple[str, ...] = (),
) -> str:
    """Non-LLM fallback — [1]…[7] only when user explicitly asks for full breakdown."""
    sections = _build_analyst_section_map(
        question=question, ctx=ctx, prior_messages=prior_messages
    )
    return format_senior_analyst_sections(sections)


def compose_direct_analyst_reply(
    *,
    question: str,
    ctx: AdvisorContext,
    prior_messages: tuple[str, ...] = (),
) -> str:
    """Non-LLM fallback — direct prose grounded in platform snapshot (no [1]…[7])."""
    intent = parse_question_intent(question)
    lead = primary_intent(intent, question)
    sections = _build_analyst_section_map(
        question=question, ctx=ctx, prior_messages=prior_messages
    )

    if lead == QuestionIntent.MARKET_DATA:
        return sections["1"].strip()

    parts: list[str] = [sections["1"]]
    if lead in (QuestionIntent.FORECAST, QuestionIntent.TIMEFRAME):
        parts.append(sections["5"])
    elif lead in (QuestionIntent.BUY, QuestionIntent.SELL):
        parts.append(sections["5"])
        parts.append(sections["4"])
    elif lead == QuestionIntent.RISK:
        parts.append(sections["4"])
    elif lead in (QuestionIntent.NEWS, QuestionIntent.REGULATORY, QuestionIntent.MACRO, QuestionIntent.POLITICS):
        parts.append(sections["3"])
        parts.append(sections["2"])
    else:
        parts.append(sections["5"])

    parts.append(sections["7"])

    unique_parts: list[str] = []
    seen: set[str] = set()
    for part in parts:
        text = part.strip() if part else ""
        if not text:
            continue
        key = _normalize_for_dedup(text)
        if key in seen:
            continue
        seen.add(key)
        unique_parts.append(text)
    return "\n\n".join(unique_parts)


def compose_brief_analyst_reply(
    *,
    question: str,
    ctx: AdvisorContext,
    prior_messages: tuple[str, ...] = (),
) -> str:
    """Non-LLM fallback when user asks for a direct answer without the full template."""
    intent = parse_question_intent(question)
    prior_advisor = prior_messages[-3:]
    return _structured_lead(
        question, intent, ctx, prior_messages=prior_advisor
    ).strip()


def _filter_fresh(items: list[str], prior_messages: tuple[str, ...]) -> list[str]:
    fresh: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = _normalize_for_dedup(item)[:120]
        if key in seen or _was_shown(item, prior_messages):
            continue
        seen.add(key)
        fresh.append(item)
    return fresh


def _section_factors(ctx: AdvisorContext, *, prior: tuple[str, ...]) -> EvidenceSection | None:
    payload = ctx.payload
    user_line = format_factor_exposure_user_ru(payload.factor_exposures)
    items: list[str] = [user_line] if user_line else []
    if payload.shap_top_factors:
        items.append(format_shap_plain_ru(payload.shap_top_factors))
    items = _filter_fresh(items, prior)
    return EvidenceSection("Факторная экспозиция", tuple(items)) if items else None


def _section_shap(ctx: AdvisorContext, *, prior: tuple[str, ...]) -> EvidenceSection | None:
    if not ctx.payload.shap_top_factors:
        return None
    items = _filter_fresh([format_shap_plain_ru(ctx.payload.shap_top_factors)], prior)
    return EvidenceSection("Драйверы скора (SHAP)", tuple(items)) if items else None


def _section_scenarios(ctx: AdvisorContext, *, prior: tuple[str, ...]) -> EvidenceSection | None:
    line = format_scenario_with_shock(ctx.payload.scenario_results)
    if not line or "не рассчитаны" in line:
        return None
    items = _filter_fresh([line], prior)
    return EvidenceSection("Стресс-сценарии", tuple(items)) if items else None


def _section_conflicts(ctx: AdvisorContext, *, prior: tuple[str, ...]) -> EvidenceSection | None:
    conflicts = detect_score_conflicts(ctx.payload)
    if not conflicts:
        return None
    items = _filter_fresh(conflicts[:3], prior)
    return EvidenceSection("Напряжения в данных", tuple(items)) if items else None


def _section_event_risk(ctx: AdvisorContext, *, prior: tuple[str, ...]) -> EvidenceSection | None:
    er = ctx.analysis.event_risk
    if er is None:
        return None
    items: list[str] = [
        f"EventRiskLayer: score {er.score:.0%}, "
        f"вероятность новостного импакта {er.news_impact_probability:.0%} "
        f"({er.article_count} статей).",
    ]
    if er.reason:
        items.append(er.reason)
    if er.topic_tags:
        items.append("Темы: " + ", ".join(er.topic_tags[:5]) + ".")
    items = _filter_fresh(items, prior)
    return EvidenceSection("Событийный риск", tuple(items)) if items else None


def _section_data_gaps(ctx: AdvisorContext, *, prior: tuple[str, ...]) -> EvidenceSection | None:
    gaps = ctx.analysis.data_gaps
    if not gaps:
        return None
    items = _filter_fresh(gaps[:6], prior)
    return EvidenceSection("Ограничения данных", tuple(items)) if items else None


def _section_financial(ctx: AdvisorContext, *, prior: tuple[str, ...]) -> EvidenceSection | None:
    output = ctx.output
    items: list[str] = []
    fund = ctx.fundamentals
    quote = ctx.quote

    cap = fund.get("market_cap")
    if cap is not None:
        items.append(f"Капитализация: {_format_large_number(float(cap))}.")
    price = quote.get("price")
    if price is not None:
        change = quote.get("change_pct")
        ch = f", Δ {float(change):+.2f}%" if change is not None else ""
        items.append(f"Котировка: {float(price):.2f}{ch}.")
    for key, label in (
        ("pe_ratio", "P/E"),
        ("dividend_yield", "Дивидендная доходность"),
        ("eps", "EPS"),
        ("beta", "Бета"),
        ("roe", "ROE"),
    ):
        val = fund.get(key)
        if val is not None:
            fmt = _format_pct(float(val)) if key in ("dividend_yield", "roe") else f"{float(val):.2f}"
            items.append(f"{label}: {fmt}.")

    mag = _magnitude_label(output)
    interval = output.interval_forecast
    items.append(
        f"Прогноз направления: {mag}; интервал {interval.horizon_days}д "
        f"P10…P90 {interval.p10:+.1%}…{interval.p90:+.1%}."
    )
    dist = output.distribution_forecast
    if dist.p50:
        items.append(
            f"Распределение доходности: P25 {dist.p25:+.1%}, P50 {dist.p50:+.1%}, P75 {dist.p75:+.1%}."
        )
    if output.sector_regime:
        sr = output.sector_regime
        items.append(
            f"Сектор {sr.sector}: режим {sr.regime.dominant_regime.replace('_', ' ')}, "
            f"мomentum {sr.sector_momentum:+.2f}."
        )

    items = _filter_fresh(items, prior)
    return EvidenceSection("Финансовые и рыночные факторы", tuple(items)) if items else None


def _section_regulatory(ctx: AdvisorContext, *, prior: tuple[str, ...]) -> EvidenceSection | None:
    buckets = _categorize_headlines(ctx.news_headlines)
    items: list[str] = []

    for headline in buckets["regulatory"][:4]:
        items.append(f"«{headline}»")

    event_score = ctx.output.risk_forecast.instrument_metrics.get("event_impact_score", 0.0)
    if event_score >= 0.30:
        items.append(f"Event-impact score: {event_score:.0%} — повышенная чувствительность к событиям.")
    if ctx.analysis.event_risk and ctx.analysis.event_risk.reason:
        items.append(ctx.analysis.event_risk.reason)

    scenarios = ctx.output.scenario_forecast.scenarios if ctx.output.scenario_forecast else ()
    for s in scenarios:
        if s.scenario_type in {"stress", "degraded"} and s.probability >= 0.10:
            label = s.label_ru or s.name
            narrative = s.impact_narrative_ru or ""
            items.append(f"Стресс-сценарий «{label}» ({s.probability:.0%}){': ' + narrative if narrative else ''}")

    items = _filter_fresh(items, prior)
    return EvidenceSection("Регуляторные и юридические риски", tuple(items)) if items else None


def _section_macro_politics(ctx: AdvisorContext, *, prior: tuple[str, ...]) -> EvidenceSection | None:
    items: list[str] = []
    output = ctx.output

    if ctx.macro_snippet:
        items.append(ctx.macro_snippet)
    if ctx.analysis.eu_macro_snippet:
        items.append(ctx.analysis.eu_macro_snippet)
    if output.global_regime:
        gr = output.global_regime
        dist_top = sorted(gr.distribution.items(), key=lambda x: -x[1])[:3]
        dist_text = ", ".join(f"{k.replace('_', ' ')} {v:.0%}" for k, v in dist_top)
        items.append(
            f"Глобальный режим: {gr.dominant_regime.replace('_', ' ')} "
            f"(уверенность {gr.confidence:.0%}). Распределение: {dist_text}."
        )
        if gr.credit_spread_proxy:
            items.append(f"Спред высокодоходных облигаций США: {gr.credit_spread_proxy:.2%}.")

    buckets = _categorize_headlines(ctx.news_headlines)
    for headline in (buckets["politics"] + buckets["regulatory"])[:3]:
        items.append(f"Геополитика/регуляторика: «{headline}»")

    overlay = output.scenario_forecast.overlay_breakdown if output.scenario_forecast else {}
    macro_overlay = {k: v for k, v in overlay.items() if "macro" in k.lower() or "regime" in k.lower()}
    for key, val in sorted(macro_overlay.items(), key=lambda x: -abs(x[1]))[:2]:
        if abs(val) >= 0.05:
            items.append(f"Макро-оверлей {key}: {val:+.1%}.")

    items = _filter_fresh(items, prior)
    return EvidenceSection("Макро и геополитика", tuple(items)) if items else None


def _section_news(ctx: AdvisorContext, *, prior: tuple[str, ...]) -> EvidenceSection | None:
    if not ctx.news_headlines:
        return None
    items: list[str] = []
    if ctx.analysis.news_sentiment:
        ns = ctx.analysis.news_sentiment
        items.append(
            f"Тональность новостей: позитивных {ns.positive}, негативных {ns.negative}, "
            f"нейтральных {ns.neutral} (avg {ns.avg_score:+.2f})."
        )
    corporate, external, other = _bucket_headlines_for_display(
        tuple(ctx.news_headlines),
        cap=NEWS_HEADLINE_CAP,
        ticker=ctx.payload.ticker,
    )
    if corporate:
        items.append("Корпоративные и финансовые:")
        for title in corporate:
            items.append(f"«{title}»")
    if external:
        items.append("Внешние и рыночные:")
        for title in external:
            items.append(f"«{title}»")
    if other:
        items.append("Прочее (низкая связь с тикером):")
        for title in other[:5]:
            items.append(f"«{title}»")
    items = _filter_fresh(items, prior)
    return EvidenceSection("Новости", tuple(items)) if items else None


def _section_forecast(ctx: AdvisorContext, *, prior: tuple[str, ...]) -> EvidenceSection | None:
    output = ctx.output
    items: list[str] = []
    interval = output.interval_forecast

    items.append(
        f"Горизонт {interval.horizon_days}д: P10 {interval.p10:+.1%}, "
        f"P90 {interval.p90:+.1%}, σ {interval.rolling_volatility:.1%}."
    )
    if output.point_forecast.plain_language_summary.strip():
        items.append(output.point_forecast.plain_language_summary.strip())
    if ctx.scenario_snippet:
        items.append(ctx.scenario_snippet)
    scenarios = output.scenario_forecast.scenarios if output.scenario_forecast else ()
    for s in sorted(scenarios, key=lambda x: -x.probability)[:3]:
        if s.probability < 0.08:
            continue
        label = s.label_ru or s.name
        narrative = f" — {s.impact_narrative_ru}" if s.impact_narrative_ru else ""
        items.append(f"{label} ({s.probability:.0%}, impact {s.impact:+.1%}){narrative}")

    items = _filter_fresh(items, prior)
    return EvidenceSection("Прогноз", tuple(items)) if items else None


def _section_risks(ctx: AdvisorContext, *, prior: tuple[str, ...]) -> EvidenceSection | None:
    risk = ctx.output.risk_forecast
    items: list[str] = []

    if risk.plain_language_summary.strip():
        items.append(risk.plain_language_summary.strip())

    for item in risk.risk_items[:6]:
        items.append(item.plain_language_summary)

    metrics = risk.instrument_metrics
    metric_labels = {
        "composite_risk_score": "Интегральный риск",
        "volatility_expansion_probability": "Расширение волатильности",
        "liquidity_risk_score": "Ликвидность",
        "tail_risk_score": "Хвостовой риск",
        "event_impact_score": "Event-impact",
        "correlation_shift_score": "Сдвиг корреляций",
    }
    for key, label in metric_labels.items():
        val = metrics.get(key)
        if val is not None and float(val) >= 0.25:
            items.append(f"{label}: {float(val):.0%}.")

    if risk.breached_metrics:
        items.append(f"Превышены пороги: {', '.join(risk.breached_metrics)}.")

    items = _filter_fresh(items, prior)
    return EvidenceSection("Риски", tuple(items)) if items else None


def _section_model_data(ctx: AdvisorContext, *, prior: tuple[str, ...]) -> EvidenceSection | None:
    payload = ctx.payload
    items: list[str] = [_payload_score_line(payload)]
    if payload.shap_top_factors:
        items.append(format_shap_plain_ru(payload.shap_top_factors, limit=2))
    reason = ctx.output.action_forecast.reason.strip()
    if reason:
        items.append(f"Правило модели (контекст, не совет): {reason}.")
    items = _filter_fresh(items, prior)
    return EvidenceSection("Данные модели", tuple(items)) if items else None


def _section_context(ctx: AdvisorContext, *, prior: tuple[str, ...]) -> EvidenceSection | None:
    insights = ctx.output.narrator_insights or ()
    if not insights:
        return None
    start = _question_hash("context") % len(insights)
    items = _filter_fresh([ins.text_ru for ins in list(insights)[start : start + 3]], prior)
    bullet_items = _filter_fresh(ctx.structured_bullets[:3], prior)
    combined = items + bullet_items
    return EvidenceSection("Контекст", tuple(combined)) if combined else None


def _build_research_sections(
    intent: QuestionIntent,
    ctx: AdvisorContext,
    *,
    question: str = "",
    prior_messages: tuple[str, ...],
) -> list[EvidenceSection]:
    """Multi-dimensional research sections — only sections with real data."""
    lead = primary_intent(intent, question)
    prior = prior_messages
    sections: list[EvidenceSection] = []

    builders = {
        QuestionIntent.MARKET_DATA: (
            _section_financial,
            _section_forecast,
            _section_risks,
            _section_news,
            _section_macro_politics,
        ),
        QuestionIntent.BUY: (
            _section_model_data,
            _section_shap,
            _section_risks,
            _section_conflicts,
            _section_scenarios,
        ),
        QuestionIntent.SELL: (
            _section_model_data,
            _section_risks,
            _section_conflicts,
            _section_scenarios,
        ),
        QuestionIntent.RISK: (
            _section_risks,
            _section_scenarios,
            _section_conflicts,
            _section_factors,
            _section_financial,
        ),
        QuestionIntent.FORECAST: (
            _section_forecast,
            _section_financial,
            _section_risks,
            _section_macro_politics,
        ),
        QuestionIntent.TIMEFRAME: (
            _section_forecast,
            _section_financial,
            _section_risks,
        ),
        QuestionIntent.NEWS: (
            _section_regulatory,
            _section_macro_politics,
            _section_forecast,
            _section_risks,
            _section_scenarios,
            _section_model_data,
        ),
        QuestionIntent.REGULATORY: (
            _section_regulatory,
            _section_news,
            _section_risks,
            _section_macro_politics,
        ),
        QuestionIntent.MACRO: (
            _section_macro_politics,
            _section_financial,
            _section_forecast,
            _section_news,
        ),
        QuestionIntent.POLITICS: (
            _section_macro_politics,
            _section_regulatory,
            _section_news,
            _section_risks,
        ),
        QuestionIntent.GENERAL: (
            _section_financial,
            _section_shap,
            _section_factors,
            _section_risks,
            _section_scenarios,
            _section_conflicts,
            _section_regulatory,
            _section_macro_politics,
            _section_news,
            _section_event_risk,
            _section_context,
            _section_data_gaps,
        ),
    }

    for builder in builders.get(lead, builders[QuestionIntent.GENERAL]):
        section = builder(ctx, prior=prior)
        if section and section.items:
            sections.append(section)

    seen_titles: set[str] = set()
    unique: list[EvidenceSection] = []
    for sec in sections:
        if sec.title in seen_titles:
            continue
        seen_titles.add(sec.title)
        unique.append(sec)
    return unique


def _outlook_line(ctx: AdvisorContext) -> str:
    output = ctx.output
    sym = output.symbol
    mag = _magnitude_label(output)
    interval = output.interval_forecast
    return (
        f"Краткий outlook модели по {sym}: направление «{mag}» на ~{interval.horizon_days}д "
        f"(интервал {interval.p10:+.1%}…{interval.p90:+.1%})."
    )


def _model_outlook_appendix_for_event(ctx: AdvisorContext, *, include_direction: bool) -> str:
    """Secondary model snapshot — omit conflicting direction when event rubric applies."""
    interval = ctx.output.interval_forecast
    sym = ctx.output.symbol
    if include_direction:
        return _outlook_line(ctx)
    return (
        f"Справочно по модели на ~{interval.horizon_days}д для {sym}: "
        f"интервал {interval.p10:+.1%}…{interval.p90:+.1%} (отдельно от новостного relief)."
    )


def _compose_event_reply(
    *,
    question: str,
    ctx: AdvisorContext,
    prior_messages: tuple[str, ...],
) -> str:
    from app.services.chat.event_news_interpretation import interpret_event_news

    interpretation = interpret_event_news(
        question=question,
        headlines=ctx.payload.news_titles,
        ticker=ctx.payload.ticker,
    )
    appendix = None
    if interpretation:
        appendix = _model_outlook_appendix_for_event(ctx, include_direction=False)
    direct = synthesize_event_answer(
        question,
        ticker=ctx.payload.ticker,
        headlines=ctx.payload.news_titles,
        outlook_line=_outlook_line(ctx),
        model_outlook_appendix=appendix,
    )
    lines = [direct]
    matched = headlines_matching_question(
        question,
        ctx.payload.news_titles,
    )
    if matched:
        lines.extend(["", "Подтверждение в ленте:"])
        for title in matched[:3]:
            lines.append(f"• «{title}»")
    if disclosure_needed(question, prior_messages):
        lines.extend(["", DISCLOSURE_RU])
    return "\n".join(lines)


def compose_deep_reply(
    *,
    question: str,
    ctx: AdvisorContext,
    prior_messages: tuple[str, ...] = (),
) -> str:
    intent = parse_question_intent(question)
    payload = ctx.payload
    prior_advisor = prior_messages[-3:]

    log_shap_factor_mentions(
        ticker=payload.ticker,
        question=question,
        factors=payload.shap_top_factors,
    )

    if use_structured_analyst_format(question):
        body = compose_structured_analyst_reply(
            question=question,
            ctx=ctx,
            prior_messages=prior_advisor,
        )
    elif wants_brief_direct_answer(question):
        body = compose_brief_analyst_reply(
            question=question,
            ctx=ctx,
            prior_messages=prior_advisor,
        )
    else:
        body = compose_direct_analyst_reply(
            question=question,
            ctx=ctx,
            prior_messages=prior_advisor,
        )

    lines = [finalize_advisor_reply(body)]
    if _show_chat_source_footer():
        if CHAT_SOURCE_RULE_RU:
            lines.append(CHAT_SOURCE_RULE_RU.strip())

    if disclosure_needed(question, prior_messages):
        lines.extend(["", DISCLOSURE_RU])

    return "\n".join(lines)


async def build_deep_advisor_reply(
    db: AsyncSession,
    *,
    instrument_id: int,
    symbol: str,
    user_question: str,
    prior_messages: tuple[str, ...] = (),
) -> str:
    try:
        intent = parse_question_intent(user_question)
        ctx = await gather_advisor_context(
            db,
            instrument_id=instrument_id,
            symbol=symbol,
            include_politics=politics_intent_requested(intent),
        )

        from app.services.chat.llm_advisor import try_llm_senior_analyst_answer

        llm_text = await try_llm_senior_analyst_answer(user_question, ctx)
        if llm_text:
            try:
                from app.utils.audit import AuditAction, audit

                await audit.log(
                    db,
                    action=AuditAction.CHAT_GROUNDING,
                    resource_type="chat_advisor",
                    resource_id=symbol,
                    details={
                        "question": user_question[:500],
                        "headlines": list(ctx.payload.news_titles or [])[:8],
                        "answer_preview": llm_text[:400],
                    },
                )
            except Exception as exc:
                logger.debug("Chat grounding audit skipped", error=str(exc))
            lines = [finalize_advisor_reply(llm_text.strip())]
            if _show_chat_source_footer():
                if CHAT_SOURCE_LLM_RU:
                    lines.append(CHAT_SOURCE_LLM_RU.strip())
            if _show_llm_disclosure() and disclosure_needed(user_question, prior_messages):
                lines.extend(["", DISCLOSURE_RU])
            return "\n".join(lines)

        return compose_deep_reply(
            question=user_question,
            ctx=ctx,
            prior_messages=prior_messages,
        )
    except Exception as exc:
        logger.warning(
            "Deep advisor reply failed — minimal template fallback",
            symbol=symbol,
            error=str(exc),
        )
        return (
            f"Краткий снимок по {symbol.upper()}: полный разбор временно недоступен "
            f"({type(exc).__name__}). Откройте Forecast/Cockpit или повторите вопрос через минуту."
        )
