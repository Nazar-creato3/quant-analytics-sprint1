"""Free / trial news: GNews, Newscatcher, CryptoPanic, GDELT, Finimpulse."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.core.http_proxy import httpx_client_kwargs
from app.core.logging import get_logger

logger = get_logger(__name__)


def _client() -> httpx.AsyncClient:
    kwargs = httpx_client_kwargs(foreign=True, timeout=httpx.Timeout(10.0, connect=3.0))
    return httpx.AsyncClient(**kwargs)


def _norm(
    *,
    title: str,
    url: str,
    source: str,
    published: str | None,
    summary: str = "",
) -> dict[str, Any]:
    return {
        "title": title,
        "url": url,
        "source": source,
        "published_at": published,
        "summary": summary,
    }


async def fetch_gnews(query: str, limit: int = 10) -> list[dict[str, Any]]:
    key = (settings.GNEWS_API_KEY or "").strip()
    if not key:
        return []
    try:
        async with _client() as client:
            resp = await client.get(
                "https://gnews.io/api/v4/search",
                params={"q": query, "lang": "en", "max": min(limit, 10), "apikey": key},
            )
            resp.raise_for_status()
            data = resp.json()
        out = []
        for art in data.get("articles") or []:
            out.append(
                _norm(
                    title=str(art.get("title") or ""),
                    url=str(art.get("url") or ""),
                    source="gnews",
                    published=art.get("publishedAt"),
                    summary=str(art.get("description") or ""),
                )
            )
        return out
    except Exception as exc:
        logger.debug("gnews_failed", error=str(exc)[:160])
        return []


async def fetch_newscatcher(query: str, limit: int = 10) -> list[dict[str, Any]]:
    key = (settings.NEWSCATCHER_API_KEY or "").strip()
    if not key:
        return []
    attempts = [
        ("https://v3-api.newscatcherapi.com/api/search", {"q": query, "lang": "en", "page_size": min(limit, 10)}),
        ("https://api.newscatcherapi.com/v2/search", {"q": query, "lang": "en", "page_size": min(limit, 10)}),
    ]
    for url, params in attempts:
        try:
            async with _client() as client:
                resp = await client.get(url, params=params, headers={"x-api-key": key})
                if resp.status_code >= 400:
                    continue
                data = resp.json()
            articles = data.get("articles") or data.get("data") or []
            out = []
            for art in articles:
                out.append(
                    _norm(
                        title=str(art.get("title") or ""),
                        url=str(art.get("link") or art.get("url") or ""),
                        source="newscatcher",
                        published=art.get("published_date") or art.get("pubDate"),
                        summary=str(art.get("excerpt") or art.get("summary") or ""),
                    )
                )
            if out:
                return out
        except Exception as exc:
            logger.debug("newscatcher_failed", error=str(exc)[:160])
    return []


async def fetch_cryptopanic(limit: int = 15) -> list[dict[str, Any]]:
    try:
        async with _client() as client:
            resp = await client.get(
                "https://cryptopanic.com/api/free/v1/posts/",
                params={"public": "true", "kind": "news"},
            )
            resp.raise_for_status()
            data = resp.json()
        out = []
        for art in (data.get("results") or [])[:limit]:
            title = str(art.get("title") or "")
            url = str((art.get("url") or "") if isinstance(art.get("url"), str) else (art.get("url") or {}).get("self") or "")
            out.append(_norm(title=title, url=url, source="cryptopanic", published=art.get("created_at")))
        return out
    except Exception as exc:
        logger.debug("cryptopanic_failed", error=str(exc)[:160])
        return []


async def fetch_gdelt(query: str = "stock market OR inflation OR oil", limit: int = 15) -> list[dict[str, Any]]:
    try:
        async with _client() as client:
            resp = await client.get(
                "https://api.gdeltproject.org/api/v2/doc/doc",
                params={
                    "query": query,
                    "mode": "ArtList",
                    "maxrecords": min(limit, 50),
                    "format": "json",
                    "timespan": "24h",
                    "sort": "HybridRel",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        out = []
        for art in data.get("articles") or []:
            out.append(
                _norm(
                    title=str(art.get("title") or ""),
                    url=str(art.get("url") or ""),
                    source="gdelt",
                    published=art.get("seendate"),
                    summary=str(art.get("domain") or ""),
                )
            )
        return out
    except Exception as exc:
        logger.debug("gdelt_failed", error=str(exc)[:160])
        return []


async def fetch_finimpulse(query: str, limit: int = 10) -> list[dict[str, Any]]:
    key = (settings.FINIMPULSE_API_KEY or "").strip()
    base = (settings.FINIMPULSE_BASE_URL or "https://api.finimpulse.com").rstrip("/")
    if not key:
        return []
    try:
        async with _client() as client:
            resp = await client.get(
                f"{base}/v1/news",
                params={"q": query, "limit": limit},
                headers={"Authorization": f"Bearer {key}", "X-API-Key": key},
            )
            if resp.status_code >= 400:
                return []
            data = resp.json()
        rows = data if isinstance(data, list) else data.get("data") or data.get("articles") or []
        out = []
        for art in rows[:limit]:
            if not isinstance(art, dict):
                continue
            out.append(
                _norm(
                    title=str(art.get("title") or art.get("headline") or ""),
                    url=str(art.get("url") or art.get("link") or ""),
                    source="finimpulse",
                    published=str(art.get("published_at") or art.get("date") or "") or None,
                    summary=str(art.get("summary") or art.get("body") or "")[:400],
                )
            )
        return out
    except Exception as exc:
        logger.debug("finimpulse_failed", error=str(exc)[:160])
        return []


async def fetch_apibricks_quote(ticker: str) -> dict[str, Any] | None:
    key = (settings.APIBRICKS_API_KEY or "").strip()
    if not key:
        return None
    try:
        async with _client() as client:
            resp = await client.get(
                "https://api.apibricks.io/v1/stock/quote",
                params={"symbol": ticker.upper()},
                headers={"X-API-Key": key, "Authorization": f"Bearer {key}"},
            )
            if resp.status_code >= 400:
                return None
            return resp.json()
    except Exception as exc:
        logger.debug("apibricks_failed", error=str(exc)[:160])
        return None


async def fetch_yahoo_ticker_rss(ticker: str, limit: int = 8) -> list[dict[str, Any]]:
    """Yahoo Finance headline RSS — no API key, ticker-scoped."""
    from xml.etree import ElementTree as ET

    sym = ticker.strip().upper()
    if not sym:
        return []
    try:
        async with _client() as client:
            resp = await client.get(
                "https://feeds.finance.yahoo.com/rss/2.0/headline",
                params={"s": sym, "region": "US", "lang": "en-US"},
            )
            if resp.status_code != 200 or "<item" not in resp.text:
                return []
            root = ET.fromstring(resp.text)
        out: list[dict[str, Any]] = []
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if not title:
                continue
            out.append(
                _norm(
                    title=title,
                    url=link or "#",
                    source="yahoo_rss",
                    published=item.findtext("pubDate"),
                    summary=(item.findtext("description") or "")[:280],
                )
            )
        return out
    except Exception as exc:
        logger.debug("yahoo_ticker_rss_failed", ticker=sym, error=str(exc)[:160])
        return []


async def aggregate_free_news(query: str, *, crypto: bool = False, limit: int = 20) -> list[dict[str, Any]]:
    chunks: list[list[dict[str, Any]]] = []
    # Prefer ticker RSS first — free and symbol-scoped.
    base = query.replace("-USD", "").replace("/", "").strip()
    if base and len(base) <= 12 and " " not in base:
        chunks.append(await fetch_yahoo_ticker_rss(base, limit=8))
    chunks.append(await fetch_gnews(query, limit=8))
    chunks.append(await fetch_newscatcher(query, limit=8))
    chunks.append(await fetch_finimpulse(query, limit=8))
    # GDELT: company/ticker phrase for better recall when keyed feeds are empty
    gdelt_q = f"{query} stock OR shares OR earnings" if not crypto else f"{query} crypto OR bitcoin"
    chunks.append(await fetch_gdelt(gdelt_q, limit=8))
    if crypto:
        chunks.append(await fetch_cryptopanic(limit=8))
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in chunks:
        for item in group:
            key = (item.get("url") or item.get("title") or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
    merged.sort(key=lambda r: str(r.get("published_at") or ""), reverse=True)
    return merged[:limit]
