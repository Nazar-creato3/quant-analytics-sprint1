"""news_shock score computation per instrument/sector."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from app.services.event_risk.news_impact import (
    NewsImpactAnalog,
    NewsImpactProbabilityResult,
    compute_news_impact_probability,
    extract_topic_tags,
    sentiment_magnitude_boost,
)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _macro_boost(
    macro_events: list[Any],
    *,
    as_of: datetime,
    symbol: str,
    sector: str | None,
) -> tuple[float, str | None]:
    """Return macro-event shock boost in [0, 1] and optional source id."""
    symbol_upper = symbol.upper()
    sector_lower = (sector or "").lower()
    now = _ensure_utc(as_of)
    cutoff = now - timedelta(hours=24)

    best = 0.0
    source_id: str | None = None
    for event in macro_events:
        event_at = _ensure_utc(event.event_date)
        if event_at < cutoff or event_at > now + timedelta(hours=48):
            continue
        impact = (event.impact or "medium").lower()
        if impact not in {"high", "medium"}:
            continue

        tickers = [value.upper() for value in (event.tickers_affected or [])]
        raw = event.raw_data or {}
        event_sector = str(raw.get("sector", "")).lower()
        affects = symbol_upper in tickers
        if not affects and sector_lower and event_sector and sector_lower == event_sector:
            affects = True
        if not affects and not tickers and impact == "high":
            affects = True
        if not affects:
            continue

        hours_away = abs((event_at - now).total_seconds()) / 3600
        decay = math.exp(-hours_away / 12.0)
        magnitude = 0.5 if impact == "high" else 0.25
        market_effect = float(getattr(event, "market_effect", 0.0) or 0.0)
        if market_effect < 0:
            magnitude += min(0.25, abs(market_effect) * 0.25)
        candidate = min(1.0, magnitude * decay)
        if candidate > best:
            best = candidate
            source_id = getattr(event, "id", None)

    return round(best, 4), source_id


def _aggregate_topic_tags(articles: Sequence[Any]) -> tuple[str, ...]:
    tags: set[str] = set()
    for article in articles:
        tags.update(extract_topic_tags(article))
    return tuple(sorted(tags))


def _aggregate_sentiment(articles: Sequence[Any]) -> float:
    values = [
        float(article.sentiment_score)
        for article in articles
        if getattr(article, "sentiment_score", None) is not None
    ]
    if not values:
        return 0.0
    return sum(values) / len(values)


def compute_news_impact_probability_for_target(
    articles: Sequence[Any],
    *,
    factor_exposures: Mapping[str, float],
    history: Sequence[NewsImpactAnalog],
    daily_volatility: float,
    sigma_threshold: float = 2.0,
) -> NewsImpactProbabilityResult:
    """Estimate probability of a >X-sigma move from news content and history."""
    topic_tags = _aggregate_topic_tags(articles)
    result = compute_news_impact_probability(
        topic_tags=topic_tags,
        factor_exposures=factor_exposures,
        history=history,
        daily_volatility=daily_volatility,
        sigma_threshold=sigma_threshold,
    )
    sentiment_boost = sentiment_magnitude_boost(_aggregate_sentiment(articles))
    boosted_probability = min(1.0, result.probability + sentiment_boost)
    return NewsImpactProbabilityResult(
        probability=round(boosted_probability, 4),
        analog_probability=result.analog_probability,
        factor_alignment=result.factor_alignment,
        daily_volatility=result.daily_volatility,
        sigma_threshold=result.sigma_threshold,
        topic_tags=result.topic_tags,
        matched_factors=result.matched_factors,
        analog_count=result.analog_count,
        strong_analog_count=result.strong_analog_count,
    )


def compute_news_shock_score(
    articles: list[Any],
    *,
    as_of: datetime,
    nearest_event_at: datetime | None = None,
    calendar_at_risk: bool = False,
    macro_events: list[Any] | None = None,
    symbol: str = "",
    sector: str | None = None,
    lookback_hours: int = 72,
    factor_exposures: Mapping[str, float] | None = None,
    impact_history: Sequence[NewsImpactAnalog] | None = None,
    daily_volatility: float = 0.0,
    sigma_threshold: float = 2.0,
) -> tuple[float, float, float, float, int, str, NewsImpactProbabilityResult]:
    """Return shock tuple plus structured news impact probability."""
    from app.services.equity.analytics import compute_news_impact_score

    news_impact, article_count, _ = compute_news_impact_score(
        articles,
        as_of=as_of,
        nearest_event_at=nearest_event_at,
        lookback_hours=lookback_hours,
    )

    impact_probability = compute_news_impact_probability_for_target(
        articles,
        factor_exposures=factor_exposures or {},
        history=impact_history or [],
        daily_volatility=daily_volatility,
        sigma_threshold=sigma_threshold,
    )

    base_shock = max(0.0, -float(news_impact))
    calendar_boost = 0.0
    if calendar_at_risk:
        calendar_boost = 0.35
        if nearest_event_at is not None:
            hours = abs((_ensure_utc(nearest_event_at) - _ensure_utc(as_of)).total_seconds()) / 3600
            calendar_boost = min(0.5, 0.5 * math.exp(-hours / 24.0))

    macro_boost, _ = _macro_boost(
        macro_events or [],
        as_of=as_of,
        symbol=symbol,
        sector=sector,
    )

    probability_boost = 0.0
    has_news_signal = bool(impact_probability.topic_tags) or impact_probability.analog_count > 0
    if has_news_signal:
        probability_boost = impact_probability.probability * 0.35
    score = min(1.0, base_shock + calendar_boost + macro_boost + probability_boost)
    parts: list[str] = []
    if base_shock > 0:
        parts.append(f"negative news impact {news_impact:.2f}")
    if impact_probability.probability >= 0.5:
        parts.append(f"news impact probability {impact_probability.probability:.2f}")
    if calendar_boost > 0:
        parts.append("calendar proximity risk")
    if macro_boost > 0:
        parts.append("macro event catalyst")
    reason = "; ".join(parts) if parts else "no shock signals"

    return (
        round(score, 4),
        round(news_impact, 4),
        round(calendar_boost, 4),
        round(macro_boost, 4),
        article_count,
        reason,
        impact_probability,
    )
