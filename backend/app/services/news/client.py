"""
News intelligence module.
Fetches articles, scores sentiment via FinBERT (ProsusAI/finbert) with VADER fallback,
optionally extracts events via LLM.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.services.news.license import may_store
from app.services.news.pipeline import classify_news_event, is_near_duplicate, latency_seconds, link_tickers
from app.services.pit.news_events import classify_event

logger = get_logger(__name__)

_NEWS_ARTICLE_COUNTS: dict[str, int] = {}


def last_news_article_counts() -> dict[str, int]:
    return dict(_NEWS_ARTICLE_COUNTS)

TIMEOUT = httpx.Timeout(15.0, connect=5.0)
RSS_USER_AGENT = "QuantAnalyticsNewsBot/1.0 (+https://github.com/apex-intel)"

# Free RSS feeds — no API key required (investing.com, RBC, Interfax).
RSS_FEEDS: dict[str, str] = {
    "investing_com": "https://www.investing.com/rss/news.rss",
    "rbc": "https://rssexport.rbc.ru/rbcnews/news/eco/index.rss",
    "interfax": "https://www.interfax.ru/rss.asp",
}


# ── NewsAPI client ────────────────────────────────────────────────────────────

async def _newsapi_get(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Single NewsAPI /everything call with retry/backoff on 429 and transient errors."""
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.get(
                    "https://newsapi.org/v2/everything",
                    params={**params, "apiKey": settings.NEWS_API_KEY},
                )
                resp.raise_for_status()
                return resp.json().get("articles", []) or []
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                await asyncio.sleep(2 ** attempt)
                continue
            logger.warning("NewsAPI error", status=exc.response.status_code, error=str(exc))
            return []
        except Exception as exc:
            logger.warning("NewsAPI request failed", attempt=attempt, error=str(exc))
            if attempt == 2:
                return []
            await asyncio.sleep(2 ** attempt)
    return []


async def fetch_articles(
    query: str,
    from_hours_ago: int | None = None,
    max_results: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch articles from NewsAPI.org.

    NewsAPI's free/Developer plan delays articles by ~24h, so a tight
    ``from`` window (e.g. the last 24h) can legitimately return zero rows even
    though the key is valid. We therefore (1) sort by publish time so the
    freshest available articles come first and (2) fall back to an unbounded
    query when the windowed request comes back empty — otherwise the news feed
    stays permanently empty (demo) on the free tier.
    """
    if not settings.NEWS_API_KEY:
        from app.services.news.free_feeds import aggregate_free_news

        logger.info("NEWS_API_KEY not set, using free news feeds")
        rows = await aggregate_free_news(query, limit=max_results or settings.NEWS_MAX_ARTICLES)
        return [
            {
                "title": r.get("title"),
                "description": r.get("summary"),
                "url": r.get("url"),
                "source": {"name": r.get("source")},
                "publishedAt": r.get("published_at"),
            }
            for r in rows
        ]

    hours = from_hours_ago or settings.NEWS_LOOKBACK_HOURS
    limit = max_results or settings.NEWS_MAX_ARTICLES
    page_size = min(limit, 100)
    from_dt = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

    base = {"q": query, "language": "en", "sortBy": "publishedAt", "pageSize": page_size}

    articles = await _newsapi_get({**base, "from": from_dt})
    if articles:
        logger.debug("NewsAPI fetched", query=query, count=len(articles), window_hours=hours)
        return articles

    # Fallback: drop the time window (handles free-tier delay / clock skew).
    articles = await _newsapi_get(base)
    logger.debug(
        "NewsAPI fetched (no-window fallback)", query=query, count=len(articles)
    )
    return articles


# ── RSS feeds (free, no API key) ─────────────────────────────────────────────

def _parse_rss_date(entry) -> datetime:
    if getattr(entry, "published_parsed", None):
        import time

        return datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=timezone.utc)
    if getattr(entry, "updated_parsed", None):
        import time

        return datetime.fromtimestamp(time.mktime(entry.updated_parsed), tz=timezone.utc)
    return datetime.now(timezone.utc)


async def fetch_rss_articles(max_results: int | None = None) -> list[dict[str, Any]]:
    """Fetch macro/market headlines from configured RSS feeds."""
    import feedparser

    limit = max_results or settings.NEWS_MAX_ARTICLES
    per_feed = max(5, limit // max(len(RSS_FEEDS), 1))
    items: list[dict[str, Any]] = []
    headers = {"User-Agent": RSS_USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"}

    async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers, follow_redirects=True) as client:
        for source, url in RSS_FEEDS.items():
            if not may_store(source):
                logger.info("rss_source_store_forbidden", source=source)
                continue
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                feed = feedparser.parse(resp.content)
                if getattr(feed, "bozo", False) and not feed.entries:
                    logger.warning(
                        "RSS parse warning",
                        source=source,
                        error=str(getattr(feed, "bozo_exception", "")),
                    )
                for entry in feed.entries[:per_feed]:
                    title = (entry.get("title") or "").strip()
                    link = (entry.get("link") or "").strip()
                    if not title or not link:
                        continue
                    summary = entry.get("summary") or entry.get("description") or ""
                    items.append(
                        {
                            "title": title,
                            "description": summary,
                            "url": link,
                            "source": source,
                            "publishedAt": _parse_rss_date(entry).isoformat(),
                        }
                    )
            except Exception as exc:
                logger.warning("RSS fetch failed", source=source, error=str(exc))

    items.sort(key=lambda a: a.get("publishedAt") or "", reverse=True)
    logger.info("RSS articles fetched", count=len(items))
    return items[:limit]


async def fetch_and_store_rss_news(
    db_session=None,
    max_results: int | None = None,
) -> list[dict[str, Any]]:
    """Ingest RSS headlines into news_articles (works without NEWS_API_KEY)."""
    articles = await fetch_rss_articles(max_results=max_results)
    processed: list[dict[str, Any]] = []
    seen_titles: list[str] = []
    shown_at = datetime.now(timezone.utc)

    for raw in articles:
        url = raw.get("url", "")
        title = raw.get("title") or ""
        description = raw.get("description") or ""
        source = raw.get("source", "rss")
        if not may_store(str(source)):
            continue
        if any(is_near_duplicate(title, prev) for prev in seen_titles):
            continue
        seen_titles.append(title)
        text = f"{title} {description}"

        sentiment_score, sentiment_label, sentiment_confidence, sentiment_engine = score_sentiment(text)
        tickers_in_article = extract_tickers_from_text(text)

        from app.services.news.filtering import compute_market_relevance, is_trusted_rss_source

        tickers_in_article = list(dict.fromkeys([*tickers_in_article, *link_tickers(title)]))
        event_type = classify_news_event(title)
        relevance = compute_market_relevance(text)
        if tickers_in_article:
            relevance = max(relevance, _compute_relevance(text, tickers_in_article[0]))
        elif is_trusted_rss_source(source):
            from app.services.news.filtering import is_economic_news

            # Curated macro RSS — baseline relevance without forcing a US ticker, but a general
            # agency's sport/accident headlines do not get it.
            if is_economic_news(title, description, source):
                relevance = max(relevance, 0.35)

        pub_raw = raw.get("publishedAt")
        try:
            pub_dt = (
                datetime.fromisoformat(str(pub_raw).replace("Z", "+00:00"))
                if pub_raw
                else shown_at
            )
        except ValueError:
            pub_dt = shown_at

        processed.append(
            {
                "url": url,
                "title": title,
                "description": description,
                "source": source,
                "published_at": raw.get("publishedAt"),
                "sentiment_score": sentiment_score,
                "sentiment_label": sentiment_label,
                "sentiment_confidence": sentiment_confidence,
                "sentiment_engine": sentiment_engine,
                "tickers_mentioned": tickers_in_article,
                "extracted_events": [
                    {
                        "type": event_type or classify_event(title, description or ""),
                        "engine": sentiment_engine,
                        "confidence": sentiment_confidence,
                        "label": sentiment_label,
                    }
                ],
                "relevance_score": relevance,
                "latency_sec": latency_seconds(published_at=pub_dt, shown_at=shown_at),
            }
        )

        if db_session:
            await _upsert_article(db_session, processed[-1])

    return processed


# ── Sentiment scoring ─────────────────────────────────────────────────────────

def score_sentiment(text: str) -> tuple[float, str, float, str]:
    """Score text: (signed_score, label, confidence, engine). Prefers FinBERT."""
    from app.services.news.finbert_sentiment import score_text_sentiment

    result = score_text_sentiment(text)
    return result.score, result.label, result.confidence, result.engine


def score_sentiment_vader(text: str) -> tuple[float, str]:
    """
    Score text sentiment using VADER.
    Returns (score: -1..1, label: positive/negative/neutral).
    """
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        analyzer = SentimentIntensityAnalyzer()
        scores = analyzer.polarity_scores(text)
        compound = scores["compound"]
        if compound >= 0.05:
            label = "positive"
        elif compound <= -0.05:
            label = "negative"
        else:
            label = "neutral"
        return float(compound), label
    except ImportError:
        # Fallback: simple keyword scoring
        return _simple_sentiment(text)


def _simple_sentiment(text: str) -> tuple[float, str]:
    """Minimal keyword-based fallback when VADER is unavailable."""
    text_lower = text.lower()
    positive_words = {
        "surge", "rally", "gain", "beat", "record", "growth", "profit",
        "bullish", "upgrade", "rise", "jump", "strong", "positive", "buy",
    }
    negative_words = {
        "crash", "fall", "drop", "miss", "loss", "bear", "decline",
        "downgrade", "sell", "weak", "negative", "risk", "concern", "warn",
    }
    pos = sum(1 for w in positive_words if w in text_lower)
    neg = sum(1 for w in negative_words if w in text_lower)
    total = pos + neg
    if total == 0:
        return 0.0, "neutral"
    score = (pos - neg) / total
    label = "positive" if score > 0.1 else ("negative" if score < -0.1 else "neutral")
    return round(score, 3), label


# ── LLM event extraction ──────────────────────────────────────────────────────

EXTRACTION_PROMPT = """Ты — financial event-extraction engine.
Извлеки только проверяемые события из текста ниже.
Для каждого события верни JSON-объект со следующими полями:
- event_type: тип события (earnings|rate_decision|sanctions|merger|cpi|tariff|geopolitical|macro|other)
- date: дата события (ISO format или null)
- tickers: список тикеров (может быть пустым)
- market_effect: ожидаемый рыночный эффект (bullish|bearish|neutral|unknown)
- confidence: уверенность 0.0–1.0
- summary: краткое резюме (1 предложение)

Верни ТОЛЬКО валидный JSON массив событий. Не давай советов покупать или продавать.
Если событий нет, верни пустой массив [].

Текст:
{text}
"""


async def extract_events_llm(text: str) -> list[dict[str, Any]]:
    """Extract structured events from text using configured LLM."""
    import json

    from app.services.llm.llm_service import LLMService, llm_enabled

    if not llm_enabled():
        return []

    try:
        content = await LLMService.complete(
            "news_event_extraction",
            EXTRACTION_PROMPT.format(text=text[:3000]),
            temperature=0.1,
            max_tokens=1000,
        )

        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        events = json.loads(content)
        return events if isinstance(events, list) else []
    except Exception as exc:
        logger.warning("LLM event extraction failed", error=str(exc))
        return []


# ── Ticker extraction ─────────────────────────────────────────────────────────

COMMON_TICKERS = {
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA", "SPY", "QQQ",
    "IVV", "VOO", "GLD", "TLT", "JPM", "BAC", "XOM", "CVX", "AMD", "INTC", "NFLX", "DIS",
    "BRK", "WMT", "PG", "JNJ", "V", "MA", "UNH", "HD", "MRK", "CRM", "CSCO",
    "BTC", "ETH", "BTC-USD", "ETH-USD", "SOL", "GS", "MS", "JPM", "C", "WFC", "T", "VZ", "IBM", "ORCL", "BLK",
    "SBER", "GAZP", "LKOH", "MOEX", "GMKN", "YNDX", "ROSN", "NVTK", "MTSS",
}

# Aliases so headlines without exact ticker still attach to the request symbol.
_TICKER_ALIASES: dict[str, set[str]] = {
    "QQQ": {"NASDAQ", "NASDAQ-100", "NDX", "INVESCO QQQ"},
    "SPY": {"S&P 500", "S&P500", "SPX", "SP500"},
    "IVV": {"S&P 500", "S&P500", "SPX"},
    "AAPL": {"APPLE"},
    "MSFT": {"MICROSOFT"},
    "GOOGL": {"GOOGLE", "ALPHABET"},
    "GOOG": {"GOOGLE", "ALPHABET"},
    "AMZN": {"AMAZON"},
    "META": {"FACEBOOK", "META PLATFORMS"},
    "NVDA": {"NVIDIA"},
    "TSLA": {"TESLA"},
    "SBER": {"SBERBANK", "СБЕР", "СБЕРБАНК"},
    "GAZP": {"GAZPROM", "ГАЗПРОМ"},
    "LKOH": {"LUKOIL", "ЛУКОЙЛ", "ЛУКОЙЛ"},
    "MOEX": {"MOSCOW EXCHANGE", "МОСКОВСКАЯ БИРЖА"},
    "CSCO": {"CISCO", "CISCO SYSTEMS"},
    "UNH": {"UNITEDHEALTH", "UNITED HEALTH"},
    "JPM": {"JPMORGAN", "JP MORGAN"},
    "C": {"CITIGROUP", "CITI"},
    "WFC": {"WELLS FARGO"},
    "BLK": {"BLACKROCK"},
}


def _token_in_text(text_upper: str, token: str) -> bool:
    """Word-boundary match so META does not hit METALS."""
    import re

    t = token.strip().upper()
    if not t:
        return False
    # Cyrillic letters count as word characters too: «СБЕР» must not hit «СБЕРЕЖЕНИЯ».
    word = "A-Z0-9А-ЯЁ"
    # Russian names inflect («Газпрома», «Сбербанку»): allow a short case ending.
    suffix = "[А-ЯЁ]{0,3}" if re.search("[А-ЯЁ]", t) else ""
    return bool(re.search(rf"(?<![{word}]){re.escape(t)}{suffix}(?![{word}])", text_upper))


def extract_tickers_from_text(text: str) -> list[str]:
    """Extract ticker symbols mentioned in a text."""
    import re

    found: list[str] = []
    original = text or ""
    upper = original.upper()

    def _add(sym: str) -> None:
        if sym not in found:
            found.append(sym)

    # $TICKER (cashtag) is explicit for any length.
    for m in re.findall(r"\$([A-Za-z]{1,5})\b", original):
        if m.upper() in COMMON_TICKERS:
            _add(m.upper())
    # A bare symbol must be written in capitals in the original text and be 3+ letters:
    # «MA», «MS», «T», «C» are ordinary words/abbreviations, not evidence of a ticker.
    for m in re.findall(r"(?<![A-Za-z0-9А-Яа-яЁё])([A-Z]{3,5})(?![A-Za-z0-9А-Яа-яЁё])", original):
        if m in COMMON_TICKERS:
            _add(m)
    for ticker, aliases in _TICKER_ALIASES.items():
        if any(_token_in_text(upper, a) for a in aliases):
            _add(ticker)
    return found


def clean_mentions(text: str, tickers: list[str] | None) -> list[str]:
    """Keep only tickers the text actually mentions, in first-seen order, no duplicates."""
    out: list[str] = []
    for t in tickers or []:
        sym = (t or "").strip().upper()
        if sym and sym not in out and text_matches_ticker(text or "", sym):
            out.append(sym)
    return out


def text_matches_ticker(text: str, ticker: str) -> bool:
    """True if text mentions ticker or a known alias (word-boundary safe)."""
    t = ticker.strip().upper()
    if not t:
        return False
    import re

    upper = text.upper()
    if re.search(rf"\${re.escape(t)}(?![A-Za-z0-9])", text, flags=re.IGNORECASE):
        return True
    if len(t) <= 3:
        # Short symbols (C, T, MA, SOL, GAP…) count only when written in capitals as a word.
        if re.search(rf"(?<![A-Za-z0-9А-Яа-яЁё]){re.escape(t)}(?![A-Za-z0-9А-Яа-яЁё])", text):
            return True
    elif _token_in_text(upper, t):
        return True
    aliases = _TICKER_ALIASES.get(t, set())
    return any(_token_in_text(upper, a) for a in aliases)


# ── Main entry point ──────────────────────────────────────────────────────────

async def fetch_news_sentiment(
    tickers: list[str],
    *,
    fast: bool | None = None,
) -> dict[str, float]:
    """
    For each ticker, compute aggregate sentiment from ingested news (FinBERT when scored).
    Returns dict of ticker -> sentiment score (-1 to 1).

    When ``fast=True`` (default in pipeline via PIPELINE_NEWS_FAST), only reads pre-scored
    DB aggregates — no live fetch and no FinBERT scoring at request time.
    """
    from app.core.config import settings
    from app.db.session import AsyncSessionLocal
    from app.services.news.sentiment_aggregate import fetch_finbert_sentiment_detail

    use_fast = settings.PIPELINE_NEWS_FAST if fast is None else fast

    try:
        async with AsyncSessionLocal() as session:
            detail = await fetch_finbert_sentiment_detail(session, tickers)
            db_map = {k: float(v["score"]) for k, v in detail.items()}
            _NEWS_ARTICLE_COUNTS.clear()
            _NEWS_ARTICLE_COUNTS.update({k: int(v.get("n_articles") or 0) for k, v in detail.items()})
    except Exception as exc:
        logger.debug("DB sentiment aggregate failed, falling back to live fetch", error=str(exc))
        db_map = {}

    if use_fast:
        return db_map or {t.upper(): 0.0 for t in tickers if t.strip()}

    missing = [
        t for t in tickers
        if t.strip() and abs(db_map.get(t.strip().upper(), 0.0)) < 1e-9
    ]
    if not missing:
        return db_map

    live_map = await _live_sentiment_for_tickers(missing)
    merged = {**{k.upper(): v for k, v in db_map.items()}, **live_map}
    for ticker in tickers:
        sym = ticker.strip().upper()
        if sym and sym not in merged:
            merged[sym] = 0.0
    return merged


async def _live_sentiment_for_tickers(tickers: list[str]) -> dict[str, float]:
    """Fetch headlines and score with batched FinBERT (fallback VADER per row)."""
    from app.services.news.finbert_sentiment import score_finbert_batch, score_text_sentiment

    sentiment_map: dict[str, float] = {}
    batch_size = 4
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        query = " OR ".join(batch)
        articles = await fetch_articles(query, from_hours_ago=48, max_results=24)
        if not articles:
            for ticker in batch:
                sentiment_map[ticker.upper()] = 0.0
            continue

        texts: list[str] = []
        text_meta: list[tuple[str, str]] = []
        scores_by_ticker: dict[str, list[float]] = {}
        for article in articles:
            text = (article.get("title") or "") + " " + (article.get("description") or "")
            if len(text.strip()) < 8:
                continue
            texts.append(text)
            text_meta.append((text, text.lower()))

        finbert_results = score_finbert_batch(texts) if texts else []
        for idx, (text, lower) in enumerate(text_meta):
            finbert = finbert_results[idx] if idx < len(finbert_results) else None
            for ticker in batch:
                if ticker.lower() not in lower:
                    continue
                scores_by_ticker.setdefault(ticker.upper(), []).append(
                    finbert.score if finbert is not None else score_text_sentiment(text).score
                )

        for ticker in batch:
            sym = ticker.upper()
            scores = scores_by_ticker.get(sym, [])
            sentiment_map[sym] = round(sum(scores) / len(scores), 4) if scores else 0.0
            _NEWS_ARTICLE_COUNTS[sym] = len(scores)

    return sentiment_map


async def fetch_and_store_news(
    tickers: list[str],
    db_session=None,
) -> list[dict[str, Any]]:
    """
    Fetch news, score sentiment, optionally extract events, save to DB.
    Falls back to free RSS feeds when NewsAPI key is missing or returns nothing.
    Returns processed article dicts.
    """
    all_processed: list[dict[str, Any]] = []

    if settings.NEWS_API_KEY and may_store("newsapi"):
        for ticker in tickers:
            articles = await fetch_articles(ticker, from_hours_ago=settings.NEWS_LOOKBACK_HOURS)

            for raw in articles:
                url = raw.get("url", "")
                title = raw.get("title") or ""
                description = raw.get("description") or ""
                text = f"{title} {description}"

                sentiment_score, sentiment_label, sentiment_confidence, sentiment_engine = score_sentiment(text)
                tickers_in_article = extract_tickers_from_text(text)

                events = []
                # Paid extraction per article only when explicitly enabled.
                if settings.LLM_ENABLED and settings.LLM_NEWS_EVENT_EXTRACTION and len(text) > 50:
                    events = await extract_events_llm(text)
                events.append(
                    {
                        "type": "sentiment_meta",
                        "engine": sentiment_engine,
                        "confidence": sentiment_confidence,
                        "label": sentiment_label,
                    }
                )

                processed = {
                    "url": url,
                    "title": title,
                    "description": description,
                    "source": raw.get("source", {}).get("name", "unknown"),
                    "published_at": raw.get("publishedAt"),
                    "sentiment_score": sentiment_score,
                    "sentiment_label": sentiment_label,
                    "sentiment_confidence": sentiment_confidence,
                    "sentiment_engine": sentiment_engine,
                    # Only tag the requested symbol when the article really mentions it:
                    # news APIs return loosely related stories for a query.
                    "tickers_mentioned": clean_mentions(
                        text, [*tickers_in_article, ticker] if text_matches_ticker(text, ticker) else tickers_in_article
                    ),
                    "extracted_events": events,
                    "relevance_score": _compute_relevance(text, ticker),
                }
                all_processed.append(processed)

                if db_session:
                    await _upsert_article(db_session, processed)

    if not all_processed:
        rss_processed = await fetch_and_store_rss_news(db_session=db_session)
        all_processed.extend(rss_processed)

    return all_processed


def _compute_relevance(text: str, ticker: str) -> float:
    """Market relevance score — combines ticker mention and topic filtering."""
    from app.services.news.filtering import compute_market_relevance

    base = compute_market_relevance(text, ticker)
    text_lower = text.lower()
    ticker_lower = ticker.lower()
    count = text_lower.count(ticker_lower)
    financial_keywords = ["earnings", "revenue", "profit", "loss", "guidance", "forecast"]
    keyword_hits = sum(1 for kw in financial_keywords if kw in text_lower)
    ticker_score = min(count * 0.2 + keyword_hits * 0.1, 1.0)
    return round(max(base, ticker_score), 3)


async def _upsert_article(session, article: dict) -> None:
    """Insert article into DB if URL not already present and market-relevant."""
    from sqlalchemy import select
    from app.db.models import NewsArticle
    from app.services.news.filtering import compute_market_relevance, is_market_relevant, is_trusted_rss_source

    text = f"{article.get('title', '')} {article.get('description', '')}"
    tickers = article.get("tickers_mentioned") or []
    ticker = tickers[0] if tickers else ""
    relevance = article.get("relevance_score")
    if relevance is None:
        relevance = _compute_relevance(text, ticker) if ticker else compute_market_relevance(text)
    if is_trusted_rss_source(article.get("source", "")):
        from app.services.news.filtering import is_economic_news

        if is_economic_news(article.get("title", ""), article.get("description", ""), article.get("source", "")):
            relevance = max(float(relevance), 0.35)
    if relevance < 0.15 and not is_market_relevant(text, ticker):
        return

    try:
        existing = await session.execute(
            select(NewsArticle).where(NewsArticle.url == article["url"])
        )
        if existing.scalar_one_or_none():
            return

        pub_dt = None
        if article.get("published_at"):
            try:
                pub_dt = datetime.fromisoformat(
                    article["published_at"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pub_dt = datetime.now(timezone.utc)

        description = (article.get("description") or "").strip() or None
        db_article = NewsArticle(
            title=article["title"][:1000],
            description=description[:4000] if description else None,
            url=article["url"][:2048],
            source=article["source"][:100],
            published_at=pub_dt or datetime.now(timezone.utc),
            sentiment_score=article["sentiment_score"],
            sentiment_label=article["sentiment_label"],
            tickers_mentioned=article["tickers_mentioned"],
            extracted_events=article["extracted_events"],
            relevance_score=relevance,
        )
        session.add(db_article)
        await session.commit()
    except Exception as exc:
        logger.warning("Failed to store article", url=article.get("url"), error=str(exc))
        await session.rollback()
