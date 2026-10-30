"""Aggregate FinBERT/VADER news sentiment per symbol per day and around earnings."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import NewsArticle

logger = get_logger(__name__)

EARNINGS_WINDOW_DAYS = 3


def _sentiment_meta(article: NewsArticle) -> dict[str, Any]:
    for ev in article.extracted_events or []:
        if isinstance(ev, dict) and ev.get("type") == "sentiment_meta":
            return ev
    return {}


def _article_confidence(article: NewsArticle) -> float:
    meta = _sentiment_meta(article)
    if meta.get("confidence") is not None:
        return float(meta["confidence"])
    return abs(float(article.sentiment_score or 0.0))


async def aggregate_symbol_sentiment(
    db: AsyncSession,
    symbol: str,
    *,
    as_of: datetime | None = None,
    lookback_hours: int = 48,
    earnings_window: bool = False,
) -> dict[str, Any]:
    """Daily (or earnings-window) aggregate sentiment for one watchlisted symbol."""
    sym = symbol.upper()
    end = as_of or datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    start = end - timedelta(hours=lookback_hours if not earnings_window else EARNINGS_WINDOW_DAYS * 24)

    stmt = (
        select(NewsArticle)
        .where(NewsArticle.published_at >= start, NewsArticle.published_at <= end)
        .order_by(NewsArticle.published_at.desc())
        .limit(200)
    )
    rows = (await db.execute(stmt)).scalars().all()
    matched: list[NewsArticle] = [
        a for a in rows if sym in [t.upper() for t in (a.tickers_mentioned or [])]
    ]
    if not matched:
        return {
            "symbol": sym,
            "score": 0.0,
            "label": "neutral",
            "confidence": 0.0,
            "n_articles": 0,
            "engine_counts": {},
            "earnings_window": earnings_window,
        }

    scores: list[float] = []
    confidences: list[float] = []
    engine_counts: dict[str, int] = {}
    for article in matched:
        score = float(article.sentiment_score or 0.0)
        scores.append(score)
        confidences.append(_article_confidence(article))
        engine = str(_sentiment_meta(article).get("engine") or "unknown")
        engine_counts[engine] = engine_counts.get(engine, 0) + 1

    avg_score = sum(scores) / len(scores)
    avg_conf = sum(confidences) / len(confidences)
    label = "positive" if avg_score > 0.05 else ("negative" if avg_score < -0.05 else "neutral")
    return {
        "symbol": sym,
        "score": round(avg_score, 4),
        "label": label,
        "confidence": round(avg_conf, 4),
        "n_articles": len(matched),
        "engine_counts": engine_counts,
        "earnings_window": earnings_window,
    }


async def fetch_finbert_sentiment_map(
    db: AsyncSession,
    tickers: list[str],
    *,
    as_of: datetime | None = None,
) -> dict[str, float]:
    """Symbol -> aggregate sentiment score for forecast enrichments."""
    detail = await fetch_finbert_sentiment_detail(db, tickers, as_of=as_of)
    return {sym: float(row["score"]) for sym, row in detail.items()}


async def fetch_finbert_sentiment_detail(
    db: AsyncSession,
    tickers: list[str],
    *,
    as_of: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Symbol -> {score, n_articles} so empty news is not treated as 'neutral 0'."""
    out: dict[str, dict[str, Any]] = {}
    for ticker in tickers:
        sym = ticker.strip().upper()
        if not sym:
            continue
        agg = await aggregate_symbol_sentiment(db, sym, as_of=as_of)
        out[sym] = {
            "score": float(agg.get("score") or 0.0),
            "n_articles": int(agg.get("n_articles") or 0),
        }
    return out
