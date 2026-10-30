"""Gather multi-dimensional context for forecast enrichment and AI advisor."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.schemas.ticker_analysis import TickerAnalysisPayload
from app.services.macro.sector_seed import sector_for_symbol
from app.services.prediction_hierarchy.types import ForecastOutput

logger = get_logger(__name__)

# Indicators that materially improve macro/regulatory analysis when present.
_CORE_MACRO_KEYS: tuple[str, ...] = (
    "vix",
    "cpi",
    "rate_cb",
    "dxy",
    "oil_brent",
    "unemployment",
    "hy_oas",
    "gov_10y",
    "credit_spread",
)

_OPTIONAL_MACRO_KEYS: tuple[str, ...] = (
    "rate_cb_ca",
    "cpi_ca",
    "unemployment_ca",
    "usdcad",
    "wb_world_gdp_growth",
    "wb_us_gdp_growth",
    "wb_cn_gdp_growth",
    "wb_ru_gdp_growth",
    "wb_us_inflation",
    "wb_us_current_account",
    "eu_gdp_growth",
    "eu_gdp_yoy_q",
    "eu_hicp_yoy",
    "eu_unemployment",
)

_FACTOR_RU: dict[str, str] = {
    "market_beta": "рыночная бетта",
    "sector_factor": "секторный фактор",
    "momentum": "моментум",
    "volatility_factor": "волатильность",
    "rates_sensitivity": "чувствительность к ставкам",
    "macro_shock_sensitivity": "макро-шок",
}


@dataclass(slots=True)
class NewsHeadline:
    title: str
    relevance_score: float = 0.0
    sentiment_score: float | None = None
    sentiment_label: str | None = None


@dataclass(slots=True)
class NewsSentimentSummary:
    positive: int = 0
    negative: int = 0
    neutral: int = 0
    avg_score: float = 0.0


@dataclass(slots=True)
class EventRiskSummary:
    score: float
    news_impact_probability: float
    article_count: int
    reason: str
    topic_tags: tuple[str, ...] = ()


@dataclass(slots=True)
class AnalysisContext:
    symbol: str
    news_headlines: list[NewsHeadline] = field(default_factory=list)
    news_sentiment: NewsSentimentSummary | None = None
    macro_snippet: str = ""
    eu_macro_snippet: str = ""
    macro_indicators: dict[str, float] = field(default_factory=dict)
    macro_stale_reason: str = ""
    factor_exposures: dict[str, float] = field(default_factory=dict)
    event_risk: EventRiskSummary | None = None
    data_gaps: list[str] = field(default_factory=list)
    structured_bullets: list[str] = field(default_factory=list)
    sector: str | None = None
    ticker_analysis: TickerAnalysisPayload | None = None


def compute_macro_data_gaps(indicators: dict[str, float]) -> list[str]:
    """Honest list of missing macro series that would deepen analysis."""
    gaps: list[str] = []
    for key in _CORE_MACRO_KEYS:
        if key not in indicators:
            gaps.append(f"macro_series_normalized.{key}")
    for key in _OPTIONAL_MACRO_KEYS:
        if key not in indicators:
            gaps.append(f"macro_series_normalized.{key} (optional)")
    if "credit_spread" not in indicators and not (
        indicators.get("hy_oas") is not None and indicators.get("gov_10y") is not None
    ):
        gaps.append("credit_spread.hy_vs_gov (FRED HY OAS + 10Y Treasury)")
    return gaps


def format_macro_snippet(
    indicators: dict[str, float],
    *,
    stale_reason: str = "",
    symbol: str = "",
) -> str:
    """Rich macro summary — region-aware when symbol is provided."""
    from app.services.analysis.macro_region import format_macro_snippet_for_symbol

    if symbol:
        return format_macro_snippet_for_symbol(
            symbol, indicators, stale_reason=stale_reason
        )
    return format_macro_snippet_for_symbol("SPY", indicators, stale_reason=stale_reason)


_EU_MACRO_KEYS: tuple[str, ...] = (
    "eu_gdp_growth",
    "eu_gdp_yoy_q",
    "eu_hicp_yoy",
    "eu_unemployment",
)


def eu_macro_indicator_subset(indicators: dict[str, float]) -> dict[str, float]:
    return {key: indicators[key] for key in _EU_MACRO_KEYS if key in indicators}


def format_eu_macro_snippet(indicators: dict[str, float]) -> str:
    """Euro area macro lines from registry — no invented values."""
    subset = eu_macro_indicator_subset(indicators)
    if not subset:
        return ""

    parts: list[str] = []
    gdp_a = subset.get("eu_gdp_growth")
    if gdp_a is not None:
        parts.append(f"рост ВВП еврозоны (г/г, год) {gdp_a:.1f}%")
    gdp_q = subset.get("eu_gdp_yoy_q")
    if gdp_q is not None:
        parts.append(f"ВВП еврозоны YoY (кв.) {gdp_q:.1f}%")
    hicp = subset.get("eu_hicp_yoy")
    if hicp is not None:
        parts.append(f"инфляция HICP {hicp:.1f}%")
    unemp = subset.get("eu_unemployment")
    if unemp is not None:
        parts.append(f"безработица {unemp:.1f}%")

    if not parts:
        return ""
    return "ЕС / еврозона (Eurostat): " + "; ".join(parts) + "."


def format_factor_snippet(factors: dict[str, float]) -> str:
    if not factors:
        return ""
    dominant = max(factors.items(), key=lambda item: abs(item[1]))
    if abs(dominant[1]) < 0.05:
        return ""
    label = _FACTOR_RU.get(dominant[0], dominant[0].replace("_", " "))
    return f"Доминирующий фактор: {label} (β={dominant[1]:+.2f}, FactorEngine)."


def summarize_news_sentiment(headlines: list[NewsHeadline]) -> NewsSentimentSummary | None:
    """Aggregate sentiment labels/scores from loaded headlines."""
    if not headlines:
        return None
    positive = negative = neutral = 0
    scores: list[float] = []
    for headline in headlines:
        label = (headline.sentiment_label or "").lower()
        if label == "positive":
            positive += 1
        elif label == "negative":
            negative += 1
        elif label:
            neutral += 1
        if headline.sentiment_score is not None:
            scores.append(float(headline.sentiment_score))
    avg = round(sum(scores) / len(scores), 4) if scores else 0.0
    return NewsSentimentSummary(
        positive=positive,
        negative=negative,
        neutral=neutral,
        avg_score=avg,
    )


async def _load_politics_headlines(
    db: AsyncSession,
    *,
    limit: int = 5,
) -> list[NewsHeadline]:
    """Load recent politics dataset headlines for macro/geopolitical analysis."""
    try:
        from datetime import datetime, timedelta, timezone

        from app.db.models import NewsArticle
        from app.services.news.politics_json_import import POLITICS_JSON_SOURCE

        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        stmt = (
            select(NewsArticle)
            .where(NewsArticle.source == POLITICS_JSON_SOURCE)
            .where(NewsArticle.published_at >= cutoff)
            .order_by(desc(NewsArticle.published_at))
            .limit(80)
        )
        headlines: list[NewsHeadline] = []
        seen: set[str] = set()

        for row in (await db.execute(stmt)).scalars().all():
            title = (row.title or "").strip()
            if not title or title in seen:
                continue
            seen.add(title)
            headlines.append(
                NewsHeadline(
                    title=title,
                    relevance_score=float(row.relevance_score or 0.0),
                    sentiment_score=row.sentiment_score,
                    sentiment_label=row.sentiment_label,
                )
            )
            if len(headlines) >= limit:
                break
        return headlines
    except Exception as exc:
        logger.debug("Analysis politics news load failed", error=str(exc))
        return []


async def _load_news_headlines(db: AsyncSession, symbol: str, *, limit: int = 5) -> list[NewsHeadline]:
    try:
        from datetime import datetime, timedelta, timezone

        from sqlalchemy.dialects.postgresql import JSONB

        from app.db.models import NewsArticle
        from app.services.news.client import text_matches_ticker

        cutoff = datetime.now(timezone.utc) - timedelta(days=14)
        symbol_upper = symbol.upper()
        stmt = (
            select(NewsArticle)
            .where(NewsArticle.published_at >= cutoff)
            .where(NewsArticle.tickers_mentioned.cast(JSONB).contains([symbol_upper]))
            .order_by(desc(NewsArticle.published_at))
            .limit(80)
        )
        headlines: list[NewsHeadline] = []
        seen: set[str] = set()
        for row in (await db.execute(stmt)).scalars().all():
            text = f"{row.title or ''} {row.description or ''}"
            if not text_matches_ticker(text, symbol_upper):
                continue
            title = (row.title or "").strip()
            if not title or title in seen:
                continue
            seen.add(title)
            headlines.append(
                NewsHeadline(
                    title=title,
                    relevance_score=float(row.relevance_score or 0.0),
                    sentiment_score=row.sentiment_score,
                    sentiment_label=row.sentiment_label,
                )
            )
            if len(headlines) >= limit:
                break

        if headlines:
            return headlines

        # Fallback: scan recent headlines without ticker tag
        fallback = await db.execute(
            select(NewsArticle)
            .where(NewsArticle.published_at >= cutoff)
            .order_by(desc(NewsArticle.published_at))
            .limit(120)
        )
        for row in fallback.scalars().all():
            text = f"{row.title or ''} {row.description or ''}"
            if not text_matches_ticker(text, symbol_upper):
                continue
            title = (row.title or "").strip()
            if title and title not in seen:
                seen.add(title)
                headlines.append(
                    NewsHeadline(
                        title=title,
                        relevance_score=0.0,
                        sentiment_score=row.sentiment_score,
                        sentiment_label=row.sentiment_label,
                    )
                )
            if len(headlines) >= limit:
                break
        return headlines
    except Exception as exc:
        logger.debug("Analysis news load failed", symbol=symbol, error=str(exc))
        return []


async def _load_macro_bundle(db: AsyncSession) -> tuple[dict[str, float], str]:
    try:
        from app.services.macro_registry.service import load_macro_snapshot_bundle

        bundle = await load_macro_snapshot_bundle(db)
        indicators = bundle.get("indicators") or {}
        stale = str(bundle.get("stale_reason") or "")
        return indicators, stale
    except Exception as exc:
        logger.debug("Analysis macro load failed", error=str(exc))
        return {}, ""


async def _load_factor_exposures(db: AsyncSession, instrument_id: int) -> dict[str, float]:
    try:
        from app.services.factor.engine import FactorEngine
        from app.utils.helpers import utcnow

        rows = await FactorEngine().estimate_for_instrument(
            db,
            instrument_id=instrument_id,
            as_of=utcnow(),
        )
        if not rows:
            return {}
        latest_time = max(row.time for row in rows)
        return {
            row.factor_name.value: round(float(row.beta), 4)
            for row in rows
            if row.time == latest_time
        }
    except Exception as exc:
        logger.debug("Analysis factor load failed", instrument_id=instrument_id, error=str(exc))
        return {}


async def _load_event_risk(
    db: AsyncSession,
    *,
    symbol: str,
    instrument_id: int,
) -> EventRiskSummary | None:
    try:
        from app.services.event_risk.layer import get_event_risk_layer

        sector = (sector_for_symbol(symbol) or (None, None))[0]
        assessment = await get_event_risk_layer().assess_target(
            db,
            symbol,
            instrument_id=instrument_id,
            sector=sector,
        )
        if assessment.article_count == 0 and assessment.score < 0.15:
            return None
        return EventRiskSummary(
            score=assessment.score,
            news_impact_probability=assessment.news_impact_probability,
            article_count=assessment.article_count,
            reason=assessment.reason.strip(),
            topic_tags=assessment.topic_tags,
        )
    except Exception as exc:
        logger.debug("Analysis event risk load failed", symbol=symbol, error=str(exc))
        return None


async def _load_structured_bullets(
    db: AsyncSession,
    instrument_id: int,
    symbol: str,
) -> list[str]:
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
                title = item.get("title") or item.get("label_ru") or item.get("text")
                if title:
                    bullets.append(str(title).strip())
        return bullets[:6]
    except Exception as exc:
        logger.debug("Analysis structured load failed", symbol=symbol, error=str(exc))
        return []


def _build_data_gaps(
    *,
    symbol: str,
    indicators: dict[str, float],
    news_count: int,
    factors: dict[str, float],
    output: ForecastOutput | None,
    ticker_analysis: TickerAnalysisPayload | None = None,
) -> list[str]:
    gaps = compute_macro_data_gaps(indicators)
    if news_count == 0:
        gaps.append(f"news_articles.{symbol} (нет релевантных заголовков за 14д)")
    if not factors:
        gaps.append(f"factor_exposures.{symbol} (FactorEngine — недостаточно истории)")
    if output and output.metadata.get("degraded"):
        gaps.append(f"market_ohlcv.{symbol} (мало баров — прогноз по макро)")
    if ticker_analysis and ticker_analysis.data_gaps:
        gaps.extend(ticker_analysis.data_gaps[:6])
    return gaps


async def _load_ticker_analysis(
    db: AsyncSession,
    *,
    instrument_id: int,
    symbol: str,
    output: ForecastOutput | None,
) -> TickerAnalysisPayload | None:
    try:
        from app.services.market_analysis.assembler import build_ticker_analysis_payload

        return await build_ticker_analysis_payload(
            symbol,
            db,
            instrument_id=instrument_id,
            hierarchy=output,
        )
    except Exception as exc:
        logger.debug("Ticker analysis assembly failed", symbol=symbol, error=str(exc))
        return None


async def gather_analysis_context(
    db: AsyncSession,
    *,
    instrument_id: int,
    symbol: str,
    output: ForecastOutput | None = None,
    include_structured: bool = True,
    include_politics: bool = False,
) -> AnalysisContext:
    """Load news, macro, factors, event risk in parallel for analysis surfaces."""
    normalized = symbol.strip().upper()
    sector = (sector_for_symbol(normalized) or (None, None))[0]

    news_task = asyncio.create_task(_load_news_headlines(db, normalized))
    politics_task = (
        asyncio.create_task(_load_politics_headlines(db, limit=5))
        if include_politics
        else None
    )
    macro_task = asyncio.create_task(_load_macro_bundle(db))
    factors_task = asyncio.create_task(_load_factor_exposures(db, instrument_id))
    event_task = asyncio.create_task(
        _load_event_risk(db, symbol=normalized, instrument_id=instrument_id)
    )
    structured_task = (
        asyncio.create_task(_load_structured_bullets(db, instrument_id, normalized))
        if include_structured
        else None
    )
    analysis_payload_task = asyncio.create_task(
        _load_ticker_analysis(db, instrument_id=instrument_id, symbol=normalized, output=output)
    )

    news, (indicators, stale), factors, event_risk = await asyncio.gather(
        news_task,
        macro_task,
        factors_task,
        event_task,
    )
    politics: list[NewsHeadline] = []
    if politics_task is not None:
        politics = await politics_task
    structured: list[str] = []
    if structured_task is not None:
        structured = await structured_task
    ticker_analysis = await analysis_payload_task

    eu_snippet = format_eu_macro_snippet(indicators)
    if ticker_analysis is not None and (eu_snippet or eu_macro_indicator_subset(indicators)):
        ticker_analysis = ticker_analysis.model_copy(
            update={
                "eu_macro_snippet": eu_snippet,
                "eu_macro_indicators": eu_macro_indicator_subset(indicators),
            }
        )

    if politics:
        seen_titles = {item.title for item in news}
        for headline in politics:
            if headline.title not in seen_titles:
                news.append(headline)
                seen_titles.add(headline.title)

    gaps = _build_data_gaps(
        symbol=normalized,
        indicators=indicators,
        news_count=len(news),
        factors=factors,
        output=output,
        ticker_analysis=ticker_analysis,
    )

    return AnalysisContext(
        symbol=normalized,
        news_headlines=news,
        news_sentiment=summarize_news_sentiment(news),
        macro_snippet=format_macro_snippet(
            indicators, stale_reason=stale, symbol=normalized
        ),
        eu_macro_snippet=eu_snippet,
        macro_indicators=indicators,
        macro_stale_reason=stale,
        factor_exposures=factors,
        event_risk=event_risk,
        data_gaps=gaps,
        structured_bullets=structured,
        sector=sector,
        ticker_analysis=ticker_analysis,
    )
