"""Multi-source terminal news — keyed APIs + RSS + NewsAPI + yfinance fallback."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.services.terminal_platform.market.schemas import NewsTapeRow
from app.utils.secret_redact import redact_secrets

logger = get_logger(__name__)

_DEFAULT_NEWS_SYMBOLS = ["AAPL", "MSFT", "NVDA", "SPY", "BTC-USD", "SBER"]


def _parse_pub(raw: Any) -> str:
    if hasattr(raw, "isoformat"):
        return raw.isoformat()
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return datetime.now(timezone.utc).isoformat()


async def _fetch_terminal_news_upstream(*, limit: int = 20) -> list[NewsTapeRow]:
    """Fetch headlines from upstream sources (no cache)."""
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(title: str, source: str, pub: Any, url: str | None = None, summary: str | None = None) -> None:
        key = (url or title).strip().lower()
        if not title.strip() or key in seen:
            return
        seen.add(key)
        collected.append(
            {
                "title": title.strip(),
                "source": source,
                "published_at": _parse_pub(pub),
                "url": url,
                "summary": summary,
            }
        )

    symbols = list(_DEFAULT_NEWS_SYMBOLS)

    # 1) Keyed company/market news (prefer fresher paid/free-key APIs)
    try:
        from app.services.market_data.http_providers import (
            FinnhubMarketClient,
            TiingoClient,
            key_configured,
        )
        from app.services.market_data.client import PolygonClient

        keyed_tasks: list[tuple[str, Any]] = []
        if key_configured("finnhub"):
            keyed_tasks.append(("finnhub", FinnhubMarketClient().get_news(symbols=symbols, limit=limit)))
        if key_configured("polygon"):
            keyed_tasks.append(("polygon", PolygonClient().get_news(symbols=symbols, limit=limit)))
        if key_configured("tiingo"):
            keyed_tasks.append(("tiingo", TiingoClient().get_news(symbols=symbols, limit=limit)))

        if keyed_tasks:
            import asyncio

            results = await asyncio.gather(*(t for _, t in keyed_tasks), return_exceptions=True)
            for (name, _), result in zip(keyed_tasks, results):
                if isinstance(result, Exception):
                    logger.warning(
                        "terminal keyed news failed",
                        provider=name,
                        error=redact_secrets(str(result)),
                    )
                    continue
                for raw in result or []:
                    if not isinstance(raw, dict):
                        continue
                    outlet = str(raw.get("source") or name).strip()
                    label = outlet if outlet.lower() == name else f"{outlet}/{name}"
                    _add(
                        str(raw.get("title") or ""),
                        label,
                        raw.get("published_at"),
                        raw.get("url"),
                        raw.get("summary"),
                    )
    except Exception as exc:
        logger.warning("terminal keyed news block failed", error=redact_secrets(str(exc)))

    # 2) RSS — always available, typically freshest macro headlines
    try:
        from app.services.news.client import fetch_rss_articles

        for raw in await fetch_rss_articles(max_results=limit):
            _add(
                str(raw.get("title") or ""),
                str(raw.get("source") or "rss"),
                raw.get("publishedAt"),
                raw.get("url"),
                raw.get("description"),
            )
    except Exception as exc:
        logger.warning("terminal RSS news failed", error=redact_secrets(str(exc)))

    try:
        from app.services.news.free_feeds import aggregate_free_news

        for raw in await aggregate_free_news("stock market OR bitcoin OR inflation", crypto=True, limit=limit):
            _add(
                str(raw.get("title") or ""),
                str(raw.get("source") or "feed"),
                raw.get("published_at"),
                raw.get("url"),
                raw.get("summary"),
            )
    except Exception as exc:
        logger.warning("terminal free news failed", error=redact_secrets(str(exc)))

    # 3) NewsAPI — when keyed (may lag on free tier)
    if (settings.NEWS_API_KEY or "").strip():
        try:
            from app.services.news.client import fetch_articles

            for raw in await fetch_articles(
                "stock market OR bitcoin OR federal reserve OR MOEX OR S&P",
                from_hours_ago=72,
                max_results=limit,
            ):
                _add(
                    str(raw.get("title") or ""),
                    str((raw.get("source") or {}).get("name") or "newsapi"),
                    raw.get("publishedAt"),
                    raw.get("url"),
                    raw.get("description"),
                )
        except Exception as exc:
            logger.warning("terminal NewsAPI fetch failed", error=redact_secrets(str(exc)))

    # 4) ProviderRouter fallback (FMP / Alpha Vantage / yfinance)
    try:
        from app.services.terminal_platform.factory import get_terminal_router

        result = await get_terminal_router().get_news(
            symbols=symbols,
            limit=limit,
        )
        if result.success and result.data:
            items = result.data if isinstance(result.data, list) else []
            for n in items:
                title = getattr(n, "title", None) or (n.get("title") if isinstance(n, dict) else None)
                if not title:
                    continue
                pub = getattr(n, "published_at", None) or (n.get("published_at") if isinstance(n, dict) else None)
                url = getattr(n, "url", None) or (n.get("url") if isinstance(n, dict) else None)
                source = getattr(n, "source", None) or (n.get("source") if isinstance(n, dict) else "yfinance")
                provider = getattr(n, "provider", None) or (n.get("provider") if isinstance(n, dict) else None)
                label = f"{source}" if not provider else f"{source}/{provider}"
                summary = getattr(n, "summary", None) or (n.get("summary") if isinstance(n, dict) else None)
                _add(str(title), str(label), pub, url, summary)
    except Exception as exc:
        logger.warning("terminal router news failed", error=redact_secrets(str(exc)))

    collected.sort(key=lambda x: x.get("published_at") or "", reverse=True)

    if not collected:
        collected = await _fetch_db_news_fallback(limit=limit)

    out: list[NewsTapeRow] = []
    for i, n in enumerate(collected[:limit]):
        title = n["title"]
        out.append(
            NewsTapeRow(
                id=f"news-{i}-{hash(title) & 0xFFFF:x}",
                headline=title,
                source=str(n.get("source") or "unknown"),
                published_at=str(n.get("published_at") or datetime.now(timezone.utc).isoformat()),
                url=n.get("url"),
                summary=n.get("summary"),
            )
        )
    return out


async def fetch_terminal_news_multi(*, limit: int = 20, force_refresh: bool = False) -> list[NewsTapeRow]:
    """
    Merge headlines newest-first; dedupe by URL/title.

    Cached for 15 min — ``last_refreshed_at`` tracks upstream fetch time, not HTTP request time.
    """
    from app.services.terminal_platform.market.feed_freshness import (
        freshness_from_news_cache,
        set_cached_news,
    )

    if not force_refresh:
        cached_rows, _meta = freshness_from_news_cache(allow_stale_serve=True)
        if cached_rows is not None:
            return list(cached_rows[:limit])

    rows = await _fetch_terminal_news_upstream(limit=limit)
    set_cached_news(rows)
    return rows


async def _fetch_db_news_fallback(*, limit: int) -> list[dict[str, Any]]:
    """Use ingested news_articles when live RSS/API paths return nothing."""
    try:
        from sqlalchemy import desc, select

        from app.db.models import NewsArticle
        from app.db.session import AsyncSessionLocal
        from app.services.news.filtering import TRUSTED_RSS_SOURCES

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(NewsArticle)
                .where(NewsArticle.source.in_(sorted(TRUSTED_RSS_SOURCES)))
                .order_by(desc(NewsArticle.published_at))
                .limit(limit)
            )
            rows = list(result.scalars().all())
            if not rows:
                result = await session.execute(
                    select(NewsArticle).order_by(desc(NewsArticle.published_at)).limit(limit)
                )
                rows = list(result.scalars().all())
    except Exception as exc:
        logger.warning("terminal db news fallback failed", error=redact_secrets(str(exc)))
        return []

    out: list[dict[str, Any]] = []
    for article in rows:
        pub = article.published_at
        out.append(
            {
                "title": article.title,
                "source": f"{article.source}/db",
                "published_at": pub.isoformat() if pub else datetime.now(timezone.utc).isoformat(),
                "url": article.url,
                "summary": article.description,
            }
        )
    if out:
        logger.info("terminal db news fallback", count=len(out))
    return out
