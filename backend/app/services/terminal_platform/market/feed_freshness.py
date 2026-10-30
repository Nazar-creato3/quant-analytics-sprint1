"""Freshness tracking for Terminal news & economic calendar feeds."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from app.services.terminal_platform.market.schemas import FeedFreshnessBlock

# News should refresh every 15–30 min; alert if stale beyond 1 hour.
NEWS_EXPECTED_INTERVAL_SEC = 30 * 60
NEWS_STALE_AFTER_SEC = 60 * 60
CALENDAR_EXPECTED_INTERVAL_SEC = 30 * 60
CALENDAR_STALE_AFTER_SEC = 60 * 60
NEWS_CACHE_TTL_SEC = 15 * 60


@dataclass
class _CachedFeed:
    rows: list[Any]
    last_refreshed_at: datetime
    newest_item_at: Optional[datetime] = None


_news_cache: Optional[_CachedFeed] = None
_calendar_cache: Optional[_CachedFeed] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str) and raw.strip():
        text = raw.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _newest_ts(items: Sequence[Any], *, attr: str) -> Optional[datetime]:
    best: Optional[datetime] = None
    for item in items:
        if isinstance(item, dict):
            raw = item.get(attr)
        else:
            raw = getattr(item, attr, None)
        ts = _parse_ts(raw)
        if ts is not None and (best is None or ts > best):
            best = ts
    return best


def build_freshness_meta(
    items: Sequence[Any],
    *,
    refreshed_at: datetime,
    ts_attr: str = "published_at",
    stale_after_sec: int = NEWS_STALE_AFTER_SEC,
    expected_interval_sec: int = NEWS_EXPECTED_INTERVAL_SEC,
    from_cache: bool = False,
) -> FeedFreshnessBlock:
    now = _utcnow()
    age_sec = max(0.0, (now - refreshed_at).total_seconds())
    newest = _newest_ts(items, attr=ts_attr)
    is_stale = age_sec >= float(stale_after_sec)
    if not items:
        is_stale = True
    return FeedFreshnessBlock(
        last_refreshed_at=refreshed_at.isoformat(),
        newest_item_at=newest.isoformat() if newest else None,
        is_stale=is_stale,
        age_sec=round(age_sec, 1),
        stale_after_sec=stale_after_sec,
        expected_interval_sec=expected_interval_sec,
        item_count=len(items),
        from_cache=from_cache,
    )


def get_cached_news() -> Optional[_CachedFeed]:
    return _news_cache


def set_cached_news(rows: list[Any], *, refreshed_at: Optional[datetime] = None) -> FeedFreshnessBlock:
    global _news_cache
    ts = refreshed_at or _utcnow()
    newest = _newest_ts(rows, attr="published_at")
    _news_cache = _CachedFeed(rows=list(rows), last_refreshed_at=ts, newest_item_at=newest)
    return build_freshness_meta(rows, refreshed_at=ts, ts_attr="published_at", from_cache=False)


def freshness_from_news_cache(*, allow_stale_serve: bool = True) -> tuple[Optional[list[Any]], Optional[FeedFreshnessBlock]]:
    cached = _news_cache
    if cached is None:
        return None, None
    age = (_utcnow() - cached.last_refreshed_at).total_seconds()
    meta = build_freshness_meta(
        cached.rows,
        refreshed_at=cached.last_refreshed_at,
        ts_attr="published_at",
        from_cache=True,
    )
    if age <= NEWS_CACHE_TTL_SEC or (allow_stale_serve and cached.rows):
        return cached.rows, meta
    return None, meta


def get_cached_calendar() -> Optional[_CachedFeed]:
    return _calendar_cache


def set_cached_calendar(rows: list[Any], *, refreshed_at: Optional[datetime] = None) -> FeedFreshnessBlock:
    global _calendar_cache
    ts = refreshed_at or _utcnow()
    newest = _newest_ts(rows, attr="when")
    _calendar_cache = _CachedFeed(rows=list(rows), last_refreshed_at=ts, newest_item_at=newest)
    return build_freshness_meta(
        rows,
        refreshed_at=ts,
        ts_attr="when",
        stale_after_sec=CALENDAR_STALE_AFTER_SEC,
        expected_interval_sec=CALENDAR_EXPECTED_INTERVAL_SEC,
        from_cache=False,
    )


def freshness_from_calendar_cache(*, allow_stale_serve: bool = True) -> tuple[Optional[list[Any]], Optional[FeedFreshnessBlock]]:
    cached = _calendar_cache
    if cached is None:
        return None, None
    age = (_utcnow() - cached.last_refreshed_at).total_seconds()
    meta = build_freshness_meta(
        cached.rows,
        refreshed_at=cached.last_refreshed_at,
        ts_attr="when",
        stale_after_sec=CALENDAR_STALE_AFTER_SEC,
        expected_interval_sec=CALENDAR_EXPECTED_INTERVAL_SEC,
        from_cache=True,
    )
    if age <= NEWS_CACHE_TTL_SEC or (allow_stale_serve and cached.rows):
        return cached.rows, meta
    return None, meta


def simulate_stale_news_cache(*, age_sec: float = NEWS_STALE_AFTER_SEC + 60) -> FeedFreshnessBlock:
    """Test helper — inject an expired cache entry for health-check regression."""
    stale_at = _utcnow().fromtimestamp(time.time() - age_sec, tz=timezone.utc)
    fake_rows = [
        {
            "id": "stale-1",
            "headline": "Stale headline (test)",
            "source": "test",
            "published_at": stale_at.isoformat(),
        }
    ]
    set_cached_news(fake_rows, refreshed_at=stale_at)
    meta = build_freshness_meta(fake_rows, refreshed_at=stale_at, ts_attr="published_at", from_cache=True)
    assert meta.is_stale
    return meta


def freshness_metadata_dict(meta: FeedFreshnessBlock) -> dict[str, Any]:
    return meta.model_dump()
