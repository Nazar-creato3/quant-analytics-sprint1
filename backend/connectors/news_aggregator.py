"""
Apex Intel — News aggregator.
Legal RSS sources; writes directly to TimescaleDB news table.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import asyncpg
import feedparser

from settings import DATABASE_URL, NEWS_POLL_INTERVAL_SEC

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("news_aggregator")

RSS_FEEDS = {
    "investing_com": "https://www.investing.com/rss/news.rss",
    "rbc": "https://rssexport.rbc.ru/rbcnews/news/eco/index.rss",
    "interfax": "https://www.interfax.ru/rss.asp",
}


async def fetch_rss(source: str, url: str) -> list[dict]:
    def _parse():
        return feedparser.parse(url)

    feed = await asyncio.to_thread(_parse)
    items = []
    for entry in feed.entries:
        items.append(
            {
                "source": source,
                "title": entry.get("title", "").strip(),
                "url": entry.get("link", ""),
                "summary": entry.get("summary", ""),
                "published_at": _parse_date(entry),
            }
        )
    return items


def _parse_date(entry) -> datetime:
    if getattr(entry, "published_parsed", None):
        import time

        return datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=timezone.utc)
    return datetime.now(timezone.utc)


async def save_news(pool: asyncpg.Pool, items: list[dict]) -> None:
    async with pool.acquire() as conn:
        for item in items:
            try:
                await conn.execute(
                    """
                    INSERT INTO news (published_at, source, title, url, summary)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (url) DO NOTHING
                    """,
                    item["published_at"],
                    item["source"],
                    item["title"],
                    item["url"],
                    item["summary"],
                )
            except Exception as exc:
                log.warning("failed to insert news item: %s", exc)


async def run() -> None:
    pool = await asyncpg.create_pool(DATABASE_URL)

    while True:
        for source, url in RSS_FEEDS.items():
            try:
                items = await fetch_rss(source, url)
                await save_news(pool, items)
                log.info("fetched %d items from %s", len(items), source)
            except Exception as exc:
                log.warning("failed to fetch feed %s: %s", source, exc)
        await asyncio.sleep(NEWS_POLL_INTERVAL_SEC)


if __name__ == "__main__":
    asyncio.run(run())
