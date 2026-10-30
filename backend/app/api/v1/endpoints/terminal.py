"""Terminal data connector API — quote / ohlcv / macro / news / calendar / providers health."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_email, get_db
from app.core.logging import get_logger
from app.services.terminal_platform.factory import get_terminal_router
from app.services.terminal_platform.models import FetchResult, ProviderHealth
from app.services.terminal_platform.types import Timeframe

router = APIRouter(prefix="/terminal", tags=["terminal"])
logger = get_logger(__name__)

def _parse_timeframe(value: str) -> Timeframe:
    for tf in Timeframe:
        if tf.value == value:
            return tf
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Unsupported timeframe {value}",
    )


@router.get("/quote", response_model=FetchResult)
async def terminal_quote(
    symbol: str = Query(..., min_length=1, max_length=32),
    provider: Optional[str] = Query(None, description="Preferred provider name"),
) -> FetchResult:
    """Live quote via ProviderRouter fallback chain (public market read)."""
    result = await get_terminal_router().get_quote(
        symbol.strip().upper(),
        preferred_provider=provider,
    )
    return result


@router.get("/ohlcv", response_model=FetchResult)
async def terminal_ohlcv(
    symbol: str = Query(..., min_length=1, max_length=32),
    timeframe: str = Query("1d"),
    from_date: Optional[date] = Query(None, alias="from"),
    to_date: Optional[date] = Query(None, alias="to"),
    provider: Optional[str] = Query(None),
) -> FetchResult:
    """OHLCV bars via ProviderRouter (public market read)."""
    tf = _parse_timeframe(timeframe)
    end = to_date or datetime.now(timezone.utc).date()
    begin = from_date or (end - timedelta(days=90))
    result = await get_terminal_router().get_ohlcv(
        symbol.strip().upper(),
        tf,
        datetime.combine(begin, datetime.min.time(), tzinfo=timezone.utc),
        datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc),
        preferred_provider=provider,
    )
    return result


@router.get("/macro", response_model=FetchResult)
async def terminal_macro(
    series_id: str = Query(..., min_length=1, max_length=64),
    from_date: Optional[date] = Query(None, alias="from"),
    to_date: Optional[date] = Query(None, alias="to"),
    country: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
) -> FetchResult:
    """Macro series (CBR / FRED / IMF / World Bank / Rosstat)."""
    kwargs: dict[str, Any] = {"preferred_provider": provider}
    if country:
        kwargs["country"] = country
    result = await get_terminal_router().get_macro(
        series_id.strip(),
        from_date=from_date,
        to_date=to_date,
        **kwargs,
    )
    return result


@router.get("/news", response_model=FetchResult)
async def terminal_news(
    symbols: Optional[str] = Query(None, description="Comma-separated tickers"),
    limit: int = Query(20, ge=1, le=100),
    provider: Optional[str] = Query(None),
) -> FetchResult:
    """Market news — RSS + NewsAPI + yfinance multi-source (fresher than AV-only feed)."""
    from app.services.terminal_platform.market.feed_freshness import (
        build_freshness_meta,
        freshness_from_news_cache,
        get_cached_news,
    )
    from app.services.terminal_platform.market.news_fetch import fetch_terminal_news_multi
    from app.services.terminal_platform.models import NewsItem

    if provider:
        # GA16-324: without symbols do not invent AAPL/MSFT/NVDA basket.
        symbol_list = [s.strip().upper() for s in (symbols or "").split(",") if s.strip()] or None
        result = await get_terminal_router().get_news(
            symbols=symbol_list,
            limit=limit,
            preferred_provider=provider,
        )
        refreshed = datetime.now(timezone.utc)
        items = result.data if result.success and result.data else []
        freshness = build_freshness_meta(
            [{"published_at": getattr(i, "published_at", None) or (i.get("published_at") if isinstance(i, dict) else None)} for i in (items or [])],
            refreshed_at=refreshed,
        )
        result.metadata = {**(result.metadata or {}), "freshness": freshness.model_dump()}
        return result

    rows = await fetch_terminal_news_multi(limit=limit)
    cached = get_cached_news()
    refreshed_at = cached.last_refreshed_at if cached else datetime.now(timezone.utc)
    _, freshness = freshness_from_news_cache(allow_stale_serve=True)
    if freshness is None:
        freshness = build_freshness_meta(rows, refreshed_at=refreshed_at)
    items = [
        NewsItem(
            title=r.headline,
            summary=r.summary,
            source=r.source,
            url=r.url or "",
            published_at=datetime.fromisoformat(r.published_at.replace("Z", "+00:00"))
            if r.published_at
            else datetime.now(timezone.utc),
            symbols=None,
            provider=r.source,
        )
        for r in rows
    ]
    return FetchResult(
        success=bool(items),
        data=items,
        provider="multi",
        metadata={
            "sources": sorted({r.source for r in rows}),
            "freshness": freshness.model_dump(),
        },
        error=None if items else "No news from RSS/NewsAPI/yfinance",
        error_code=None if items else "EMPTY",
    )


@router.get("/calendar", response_model=FetchResult)
async def terminal_calendar(
    from_date: Optional[date] = Query(None, alias="from"),
    to_date: Optional[date] = Query(None, alias="to"),
    limit: int = Query(40, ge=1, le=200),
) -> FetchResult:
    """Economic calendar via FMP → Investing RapidAPI → free FOMC/CBR path."""
    from app.services.terminal_platform.calendar import fetch_terminal_calendar
    from app.services.terminal_platform.market.feed_freshness import (
        build_freshness_meta,
        freshness_from_calendar_cache,
        get_cached_calendar,
        set_cached_calendar,
    )

    today = datetime.now(timezone.utc).date()
    begin = from_date or today
    end = to_date or (today + timedelta(days=14))
    cached_rows, cached_meta = freshness_from_calendar_cache(allow_stale_serve=True)
    if cached_rows is not None and cached_meta is not None and not cached_meta.is_stale:
        return FetchResult(
            success=bool(cached_rows),
            data=cached_rows,
            provider="cache",
            metadata={"freshness": cached_meta.model_dump()},
        )

    result = await fetch_terminal_calendar(from_date=begin, to_date=end, limit=limit)
    items = result.data if result.success and result.data else []
    if items:
        set_cached_calendar(list(items))
        cached = get_cached_calendar()
        refreshed_at = cached.last_refreshed_at if cached else datetime.now(timezone.utc)
        freshness = build_freshness_meta(
            items,
            refreshed_at=refreshed_at,
            ts_attr="when",
            stale_after_sec=3600,
            expected_interval_sec=1800,
        )
    else:
        freshness = build_freshness_meta([], refreshed_at=datetime.now(timezone.utc), ts_attr="when")
    result.metadata = {**(result.metadata or {}), "freshness": freshness.model_dump()}
    return result


@router.get("/providers/health", response_model=list[ProviderHealth])
async def terminal_providers_health(
    _email: str = Depends(get_current_user_email),
) -> list[ProviderHealth]:
    """Health / circuit / key status for terminal data providers (session only)."""
    rows = await get_terminal_router().providers_health()
    return [r.model_copy(update={"last_error": None}) for r in rows]


@router.get("/data-health")
async def terminal_data_health(
    refresh: bool = Query(True, description="Probe key ticker freshness"),
    _email: str = Depends(get_current_user_email),
) -> dict[str, Any]:
    """Compact data health / freshness guard for Terminal Market."""
    from app.services.terminal_platform.market.data_health import run_data_health

    return await run_data_health(reset_circuits=False, refresh=refresh)


@router.post("/providers/reset-circuits")
async def terminal_reset_circuits(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Ops: clear stuck circuit_open after rate-limit storms."""
    from app.core.rbac_deps import get_user_and_role
    from app.domain.rbac import has_permission

    _user, role = await get_user_and_role(db, email)
    if not has_permission(role, "ops.read") and not has_permission(role, "*"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ops.read required")
    reset = get_terminal_router().reset_all_circuits()
    health = await get_terminal_router().providers_health()
    return {
        "reset": reset,
        "providers": [h.model_dump(mode="json") for h in health],
    }