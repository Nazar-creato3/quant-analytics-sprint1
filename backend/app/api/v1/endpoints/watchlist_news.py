"""
Watchlist CRUD and News feed endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user_email, get_db
from app.core.logging import get_logger
from app.db.models import NewsArticle, Watchlist
from app.schemas.schemas import NewsArticleOut, PaginatedResponse, WatchlistCreate, WatchlistOut
from app.utils.audit import AuditAction, audit

logger = get_logger(__name__)

# ── Watchlist ──────────────────────────────────────────────────────────────────

watchlist_router = APIRouter(prefix="/watchlists", tags=["watchlists"])


class WatchlistPinBody(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)


@watchlist_router.get("/effective")
async def get_effective_watchlist_endpoint(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list]:
    """Return the operator's resolved watchlist with auto-detected categories."""
    from app.services.settings.watchlist import get_effective_watchlist_enriched

    entries = await get_effective_watchlist_enriched(db, email)
    return {"tickers": [entry["symbol"] for entry in entries], "entries": entries}


@watchlist_router.post("/pin")
async def pin_watchlist_symbol_endpoint(
    body: WatchlistPinBody,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list]:
    """Pin an instrument from universal search onto the personal watchlist."""
    from app.services.settings.watchlist import get_effective_watchlist_enriched, pin_watchlist_symbol

    await pin_watchlist_symbol(db, email, body.symbol)
    await audit.log(db, action=AuditAction.WATCHLIST_UPDATED, details={"pin": body.symbol})
    entries = await get_effective_watchlist_enriched(db, email)
    return {"tickers": [entry["symbol"] for entry in entries], "entries": entries}


@watchlist_router.delete("/pin/{symbol:path}")
async def unpin_watchlist_symbol_endpoint(
    symbol: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list]:
    """Remove a pinned symbol from the personal watchlist."""
    from app.services.settings.watchlist import get_effective_watchlist_enriched, unpin_watchlist_symbol

    await unpin_watchlist_symbol(db, email, symbol)
    await audit.log(db, action=AuditAction.WATCHLIST_UPDATED, details={"unpin": symbol})
    entries = await get_effective_watchlist_enriched(db, email)
    return {"tickers": [entry["symbol"] for entry in entries], "entries": entries}


@watchlist_router.get("", response_model=list[WatchlistOut])
async def list_watchlists(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> list[WatchlistOut]:
    result = await db.execute(
        select(Watchlist).order_by(Watchlist.is_default.desc(), Watchlist.created_at)
    )
    return [WatchlistOut.model_validate(w) for w in result.scalars().all()]


@watchlist_router.post("", response_model=WatchlistOut, status_code=status.HTTP_201_CREATED)
async def create_watchlist(
    body: WatchlistCreate,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> WatchlistOut:
    wl = Watchlist(name=body.name, tickers=body.tickers, is_default=False)
    db.add(wl)
    await db.commit()
    await db.refresh(wl)
    await audit.log(db, action=AuditAction.WATCHLIST_UPDATED, details={"name": body.name})
    return WatchlistOut.model_validate(wl)


@watchlist_router.put("/{wl_id}", response_model=WatchlistOut)
async def update_watchlist(
    wl_id: str,
    body: WatchlistCreate,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> WatchlistOut:
    result = await db.execute(select(Watchlist).where(Watchlist.id == wl_id))
    wl = result.scalar_one_or_none()
    if not wl:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    wl.name = body.name
    wl.tickers = body.tickers
    await db.commit()
    await db.refresh(wl)
    return WatchlistOut.model_validate(wl)

@watchlist_router.delete("/{wl_id}", status_code=status.HTTP_200_OK)
async def delete_watchlist(
    wl_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(select(Watchlist).where(Watchlist.id == wl_id))
    wl = result.scalar_one_or_none()
    if not wl:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    if wl.is_default:
        raise HTTPException(status_code=400, detail="Cannot delete the default watchlist")
    await db.delete(wl)
    await db.commit()


@watchlist_router.get("/alerts")
async def list_watchlist_alerts(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    from app.db.models import WatchlistAlertRule

    result = await db.execute(
        select(WatchlistAlertRule).where(WatchlistAlertRule.user_email == email.lower())
    )
    rows = result.scalars().all()
    return [
        {
            "id": r.id,
            "symbol": r.symbol,
            "metric": r.metric,
            "threshold": r.threshold,
            "direction": r.direction,
            "enabled": r.enabled,
            "last_triggered_at": r.last_triggered_at.isoformat() if r.last_triggered_at else None,
        }
        for r in rows
    ]


@watchlist_router.post("/alerts", status_code=status.HTTP_201_CREATED)
async def upsert_watchlist_alert(
    body: dict,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.db.models import WatchlistAlertRule

    symbol = str(body.get("symbol", "")).upper().strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol required")
    threshold = float(body.get("threshold", 0.7))
    metric = str(body.get("metric", "ml_confidence"))
    direction = str(body.get("direction", "above"))
    enabled = bool(body.get("enabled", True))

    result = await db.execute(
        select(WatchlistAlertRule).where(
            WatchlistAlertRule.user_email == email.lower(),
            WatchlistAlertRule.symbol == symbol,
            WatchlistAlertRule.metric == metric,
            WatchlistAlertRule.direction == direction,
        )
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        rule = WatchlistAlertRule(
            user_email=email.lower(),
            symbol=symbol,
            metric=metric,
            threshold=threshold,
            direction=direction,
            enabled=enabled,
        )
        db.add(rule)
    else:
        rule.threshold = threshold
        rule.enabled = enabled
    await db.commit()
    await db.refresh(rule)
    return {
        "id": rule.id,
        "symbol": rule.symbol,
        "metric": rule.metric,
        "threshold": rule.threshold,
        "direction": rule.direction,
        "enabled": rule.enabled,
    }


# ── News ───────────────────────────────────────────────────────────────────────

news_router = APIRouter(prefix="/news", tags=["news"])


@news_router.get("", response_model=PaginatedResponse)
async def list_news(
    ticker: str | None = Query(None, description="Filter by ticker mention"),
    sentiment: str | None = Query(None, pattern="^(positive|negative|neutral)$"),
    min_relevance: float = Query(0.15, ge=0.0, le=1.0),
    locale: str = Query("ru", description="Locale for title/summary (ru = machine translation)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(settings.NEWS_PANEL_SIZE, ge=1, le=100),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse:
    """List ingested news articles with optional filters."""
    from sqlalchemy import desc, func, or_
    from sqlalchemy.dialects.postgresql import JSONB

    from app.services.news.client import fetch_and_store_news, text_matches_ticker
    from app.services.news.filtering import TRUSTED_RSS_SOURCES

    ticker_u = ticker.upper().strip() if ticker else None

    query = select(NewsArticle).order_by(desc(NewsArticle.published_at))

    if ticker_u:
        # Prefer exact JSON tag; do NOT use substring ILIKE (META matches METALS).
        query = query.where(
            NewsArticle.tickers_mentioned.cast(JSONB).contains([ticker_u])
        )
    if sentiment:
        query = query.where(NewsArticle.sentiment_label == sentiment)
    query = query.where(NewsArticle.relevance_score >= min_relevance)

    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()

    # On-demand targeted ingest when empty for a symbol (NewsAPI or RSS+tag).
    if total == 0 and ticker_u:
        try:
            await fetch_and_store_news(tickers=[ticker_u], db_session=db)
            count_result = await db.execute(select(func.count()).select_from(query.subquery()))
            total = count_result.scalar_one()
        except Exception as exc:
            logger.warning("On-demand ticker news fetch failed", ticker=ticker_u, error=str(exc))

    # On-demand RSS backfill when the DB is empty (no NEWS_API_KEY required).
    if total == 0:
        try:
            from app.services.news.client import fetch_and_store_rss_news

            await fetch_and_store_rss_news(db_session=db)
            count_result = await db.execute(select(func.count()).select_from(query.subquery()))
            total = count_result.scalar_one()
        except Exception as exc:
            logger.warning("On-demand RSS news fetch failed", error=str(exc))

    # Soft match: scan recent articles and attach ticker when aliases match.
    if total == 0 and ticker_u:
        try:
            recent = await db.execute(
                select(NewsArticle)
                .order_by(desc(NewsArticle.published_at))
                .limit(250)
            )
            tagged = 0
            for article in recent.scalars().all():
                text = f"{article.title or ''} {article.description or ''}"
                if not text_matches_ticker(text, ticker_u):
                    continue
                mentioned = list(article.tickers_mentioned or [])
                if ticker_u not in mentioned:
                    mentioned.append(ticker_u)
                    article.tickers_mentioned = mentioned
                    tagged += 1
            if tagged:
                await db.commit()
                count_result = await db.execute(select(func.count()).select_from(query.subquery()))
                total = count_result.scalar_one()
        except Exception as exc:
            logger.warning("Ticker soft-tag failed", ticker=ticker_u, error=str(exc))

    # Legacy rows may have low relevance scores from pre-filter deploy — still show trusted RSS.
    if total == 0:
        fallback_query = select(NewsArticle).order_by(desc(NewsArticle.published_at))
        if ticker_u:
            fallback_query = fallback_query.where(
                NewsArticle.tickers_mentioned.cast(JSONB).contains([ticker_u])
            )
        if sentiment:
            fallback_query = fallback_query.where(NewsArticle.sentiment_label == sentiment)
        fallback_query = fallback_query.where(
            or_(
                NewsArticle.relevance_score >= min_relevance,
                NewsArticle.source.in_(sorted(TRUSTED_RSS_SOURCES)),
            )
        )
        count_result = await db.execute(
            select(func.count()).select_from(fallback_query.subquery())
        )
        total = count_result.scalar_one()
        if total > 0:
            query = fallback_query

    # Fetch a wider window then drop false-positive tags (e.g. META ⊂ METALS).
    offset = (page - 1) * page_size
    fetch_n = page_size * 4
    result = await db.execute(query.offset(offset).limit(fetch_n))
    from app.services.news.filtering import is_economic_news

    # Rows stored before the economic filter: drop sport/accident headlines from general agencies.
    raw_articles = [
        a for a in result.scalars().all()
        if is_economic_news(a.title or "", a.description or "", a.source or "")
    ]
    dirty_tags = False
    if ticker_u:
        articles = []
        for article in raw_articles:
            text = f"{article.title or ''} {article.description or ''}"
            if text_matches_ticker(text, ticker_u):
                articles.append(article)
                continue
            mentioned = list(article.tickers_mentioned or [])
            if ticker_u in mentioned:
                article.tickers_mentioned = [t for t in mentioned if t != ticker_u]
                dirty_tags = True
        articles = articles[:page_size]
        if dirty_tags:
            try:
                await db.commit()
            except Exception:
                await db.rollback()
        total = len(articles) if offset == 0 else max(total, len(articles))
    else:
        articles = raw_articles[:page_size]

    from app.services.news.translation import localize_news_articles

    localized = await localize_news_articles(articles, locale=locale)

    return PaginatedResponse(
        items=localized,
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, (total + page_size - 1) // page_size) if total else 1,
    )


@news_router.post("/fetch", status_code=202)
async def trigger_news_fetch(
    tickers: list[str] | None = None,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually trigger news ingestion for given tickers."""
    from app.tasks.data_ingestion import ingest_news_task
    from app.services.settings.watchlist import get_effective_watchlist

    watchlist = tickers or await get_effective_watchlist(db, email)
    try:
        ingest_news_task.delay(tickers=watchlist)
        return {"status": "queued", "tickers": watchlist}
    except Exception as exc:
        logger.warning("news fetch queue failed", error=str(exc))
        raise HTTPException(status_code=503, detail="Нет данных") from exc
