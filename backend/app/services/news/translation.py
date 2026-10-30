"""Machine translation for news headlines and summaries (RU locale)."""
from __future__ import annotations

import json
import re
from typing import Any

from app.core.logging import get_logger
from app.db.models import NewsArticle
from app.schemas.schemas import NewsArticleOut
from app.utils.cache import cache_get, cache_set

logger = get_logger(__name__)

_RUSSIAN_SOURCES = frozenset(
    {"rbc", "interfax", "рбк", "интерфакс", "tass", "ria", "коммерсант", "vedomosti"}
)
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_CACHE_TTL = 7 * 24 * 3600


def _cyrillic_ratio(text: str) -> float:
    if not text.strip():
        return 0.0
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    cyrillic = sum(1 for ch in letters if _CYRILLIC_RE.match(ch))
    return cyrillic / len(letters)


def _is_russian_source(source: str) -> bool:
    normalized = source.strip().lower()
    return any(token in normalized for token in _RUSSIAN_SOURCES)


def _cache_key(article_id: str) -> str:
    return f"news:tr:ru:{article_id}"


async def _translate_via_llm(title: str, summary: str) -> dict[str, str] | None:
    from app.services.llm.llm_service import LLMService, llm_enabled

    from app.core.config import settings

    # Auto-translation of every new headline is a background cost; opt-in only.
    if not settings.LLM_NEWS_TRANSLATION or not llm_enabled():
        return None

    payload = json.dumps({"title": title, "summary": summary or ""}, ensure_ascii=False)
    system = (
        "You are a financial news translator. Translate English financial news into Russian. "
        "Return ONLY valid JSON: {\"title\": \"...\", \"summary\": \"...\"}. "
        "Keep tickers, numbers, and company names accurate. Summary may be empty string."
    )
    try:
        raw = await LLMService.complete(
            "news_translate",
            payload,
            system=system,
            temperature=0.1,
            max_tokens=900,
        )
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1]
            if cleaned.lstrip().startswith("json"):
                cleaned = cleaned.lstrip()[4:]
        parsed = json.loads(cleaned.strip())
        if isinstance(parsed, dict) and parsed.get("title"):
            return {
                "title": str(parsed["title"]).strip(),
                "summary": str(parsed.get("summary") or "").strip(),
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("News MT failed", error=str(exc))
    return None


async def localize_news_article(article: NewsArticle, *, locale: str = "ru") -> NewsArticleOut:
    """Build NewsArticleOut with optional RU machine translation."""
    summary = (article.description or "").strip()
    base = NewsArticleOut(
        id=article.id,
        title=article.title,
        description=summary or None,
        url=article.url,
        source=article.source,
        published_at=article.published_at,
        sentiment_score=article.sentiment_score,
        sentiment_label=article.sentiment_label,
        tickers_mentioned=list(article.tickers_mentioned or []),
        relevance_score=float(article.relevance_score or 0.0),
    )

    if locale.lower() != "ru":
        return base

    if _is_russian_source(article.source) or _cyrillic_ratio(article.title) >= 0.35:
        return base.model_copy(
            update={
                "title_ru": article.title,
                "summary_ru": summary or None,
                "is_machine_translated": False,
            }
        )

    cached: dict[str, Any] | None = await cache_get(_cache_key(article.id))
    if cached and cached.get("title_ru"):
        return base.model_copy(
            update={
                "title_ru": cached["title_ru"],
                "summary_ru": cached.get("summary_ru") or None,
                "is_machine_translated": bool(cached.get("is_machine_translated", True)),
            }
        )

    translated = await _translate_via_llm(article.title, summary)
    if not translated:
        return base

    title_ru = translated["title"]
    summary_ru = translated.get("summary") or None
    await cache_set(
        _cache_key(article.id),
        {
            "title_ru": title_ru,
            "summary_ru": summary_ru,
            "is_machine_translated": True,
        },
        ttl=_CACHE_TTL,
    )
    return base.model_copy(
        update={
            "title_ru": title_ru,
            "summary_ru": summary_ru,
            "is_machine_translated": True,
        }
    )


async def localize_news_articles(
    articles: list[NewsArticle],
    *,
    locale: str = "ru",
) -> list[NewsArticleOut]:
    results: list[NewsArticleOut] = []
    for article in articles:
        results.append(await localize_news_article(article, locale=locale))
    return results
