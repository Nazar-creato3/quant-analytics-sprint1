"""
Market data, audit logs, and system health endpoints.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user_email, get_current_user_payload, get_db
from app.core.logging import get_logger
from app.core.ui_features import raise_if_ui_removed
from app.utils.json_safe import sanitize_for_json
from app.db.models import AuditLog, BacktestRun, OHLCVBar
from app.schemas.schemas import (
    AuditLogOut,
    BacktestRequest,
    BacktestResultOut,
    HealthResponse,
    OHLCVBarOut,
    PaginatedResponse,
)

logger = get_logger(__name__)

# тФАтФА Health тФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФА

health_router = APIRouter(prefix="/health", tags=["system"])


@health_router.get("/live")
async def liveness_check() -> dict[str, str]:
    """Liveness probe that does not depend on external services."""
    return {"status": "ok"}


@health_router.get("")
async def health_check(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """System health check — tests DB and Redis connectivity.

    Public (no auth). Status values are coarse (``ok`` / ``error``) so
    exception strings are never leaked to anonymous callers (SEC-08).
    """
    db_status = "ok"
    redis_status = "ok"

    try:
        await db.execute(select(1))  # type: ignore
    except Exception as exc:
        logger.warning("Health DB check failed", error=str(exc))
        db_status = "error"

    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        await r.ping()
        await r.aclose()
    except Exception as exc:
        logger.warning("Health Redis check failed", error=str(exc))
        redis_status = "error"

    mode = "paper" if settings.PAPER_TRADING_ENABLED else ("live" if settings.live_trading_unlocked else "disabled")
    overall = "ok" if db_status == "ok" and redis_status == "ok" else "error"
    payload = HealthResponse(
        status=overall,
        db=db_status,
        redis=redis_status,
        trading_mode=mode,
    )
    return JSONResponse(
        status_code=200 if overall == "ok" else 503,
        content=payload.model_dump(),
    )


# тФАтФА Market Data тФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФА

market_router = APIRouter(prefix="/market", tags=["market"])


def _adjust_chart_bars(
    bars: list[OHLCVBarOut], adjust: str, timeframe: str = "1d"
) -> list[OHLCVBarOut]:
    if not bars or adjust == "raw":
        return bars
    # Adjustment is keyed by session date: on intraday bars every bar of a day
    # would get that day's last close (flat «dash» candles). Corporate actions
    # are not passed here, so the scale is 1 anyway — intraday stays raw.
    if timeframe not in ("1d", "1w"):
        return bars
    from datetime import date
    from decimal import Decimal

    from app.services.market_data.series import OhlcBar, adjust_ohlc

    ohlc: list[OhlcBar] = []
    for bar in bars:
        ts = bar.timestamp
        session = ts.date() if hasattr(ts, "date") else date.fromisoformat(str(ts)[:10])
        ohlc.append(
            OhlcBar(
                session,
                Decimal(str(bar.open)),
                Decimal(str(bar.high)),
                Decimal(str(bar.low)),
                Decimal(str(bar.close)),
                Decimal(str(bar.volume or 0)),
            )
        )
    adj = adjust_ohlc(ohlc, [], adjust)  # type: ignore[arg-type]
    by_day = {item.session_date: item for item in adj}
    out: list[OHLCVBarOut] = []
    for bar in bars:
        ts = bar.timestamp
        session = ts.date() if hasattr(ts, "date") else date.fromisoformat(str(ts)[:10])
        scaled = by_day.get(session)
        if scaled is None:
            out.append(bar)
            continue
        out.append(
            bar.model_copy(
                update={
                    "open": float(scaled.open),
                    "high": float(scaled.high),
                    "low": float(scaled.low),
                    "close": float(scaled.close),
                }
            )
        )
    return out


@market_router.get("/bars/{ticker}", response_model=list[OHLCVBarOut])
async def get_bars(
    ticker: str,
    timeframe: str = Query("1d", pattern="^(1m|5m|15m|1h|4h|1d|1w)$"),
    limit: int = Query(100, ge=1, le=1000),
    force_refresh: bool = Query(False, description="Bypass Redis bar cache and refetch from provider"),
    adjust: str = Query("split_adj", pattern="^(raw|split_adj|total_return)$"),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> list[OHLCVBarOut]:
    """Get OHLCV bars тАФ local DB with on-demand provider fetch and Redis cache.

    Crypto last bar is always patched with live Binance spot (WS or REST).
    Degrades gracefully: any backend/provider hiccup returns an empty list
    (HTTP 200) instead of a 500 so the chart shows a clean "no data" state
    rather than an error banner.
    """
    from app.services.market_data.bars import get_bars_for_chart

    from app.services.market_data.moex_spot import is_moex_ticker, normalize_moex_symbol

    symbol = normalize_moex_symbol(ticker) if is_moex_ticker(ticker) else ticker.upper()
    try:
        bars = await get_bars_for_chart(
            db, symbol, timeframe, limit, force_refresh=force_refresh
        )
        return _adjust_chart_bars(bars, adjust, timeframe)
    except Exception as exc:
        logger.warning("Bars endpoint failed", ticker=ticker, timeframe=timeframe, error=str(exc))
        return []


@market_router.get("/name-card/{ticker}")
async def get_name_card(
    ticker: str,
    direction: str | None = Query(None),
    email: str = Depends(get_current_user_email),
) -> dict:
    """Price, filings, shorts, news, and a human why — one desk for the selected name."""
    from app.services.market_data.moex_spot import is_moex_ticker, normalize_moex_symbol
    from app.services.market_data.name_card import build_name_card

    symbol = normalize_moex_symbol(ticker) if is_moex_ticker(ticker) else ticker.upper()
    return sanitize_for_json(await build_name_card(symbol, direction=direction))


@market_router.get("/overview")
async def get_market_overview(email: str = Depends(get_current_user_email)) -> dict:
    """Today's markets board: indices, sectors, FX, commodities, news, regime."""
    from app.services.market_data.market_overview import build_market_overview

    return sanitize_for_json(await build_market_overview())


@market_router.get("/analysis")
async def get_market_analysis(email: str = Depends(get_current_user_email)) -> dict:
    """Prompt 45: indices/regime/breadth/corr from canonical services."""
    from app.services.market_analysis.service import overview as analysis_overview

    return sanitize_for_json(analysis_overview())


@market_router.get("/quote/{ticker}")
async def get_live_quote(
    ticker: str,
    force_refresh: bool = Query(False, description="Bypass quote cache and fetch fresh from provider"),
    enrich: bool = Query(
        False,
        description=(
            "Optional bars/fundamentals enrichment. Default off so watchlist/header "
            "quotes stay within FE timeout; enable for Info tabs."
        ),
    ),
    email: str = Depends(get_current_user_email),
    payload: dict = Depends(get_current_user_payload),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Fetch a live quote тАФ Binance for crypto, MOEX for RU, Alpaca/chain for US.

    Fast path returns provider price/change immediately. Heavy enrichment (252 daily
    bars + FMP/yfinance fundamentals) is opt-in and soft-budgeted so concurrent
    watchlist fan-out cannot stall the UI for minutes.
    """
    import asyncio

    from app.services.market_data.moex_spot import is_moex_ticker, normalize_moex_symbol

    symbol = normalize_moex_symbol(ticker) if is_moex_ticker(ticker) else ticker.upper()
    try:
        from app.services.market_data.bars import get_bars_for_chart
        from app.services.market_data.client import get_latest_quote_resolved
        from app.services.market_data.enrichment import enrich_symbol_metadata
        from app.services.market_data.quote_utils import enrich_quote_fields, extract_quote_price

        quote = await get_latest_quote_resolved(symbol, force_refresh=force_refresh)
        quote = enrich_quote_fields(dict(quote), None)
        price = extract_quote_price(quote)
        if price is not None:
            quote["price"] = price

        if enrich:
            async def _enrich() -> None:
                nonlocal quote
                bars = await get_bars_for_chart(db, symbol, "1d", 252)
                enrichment = await enrich_symbol_metadata(symbol, bars)
                merged = enrich_quote_fields(dict(quote), bars)
                if enrichment.get("fundamentals"):
                    merged["fundamentals"] = enrichment["fundamentals"]
                if enrichment.get("technical"):
                    merged["technical"] = enrichment["technical"]
                priced = extract_quote_price(merged)
                if priced is not None:
                    merged["price"] = priced
                quote = merged

            try:
                await asyncio.wait_for(_enrich(), timeout=4.0)
            except asyncio.TimeoutError:
                logger.info("Quote enrichment timed out; returning fast quote", ticker=symbol)
            except Exception as enrich_exc:
                logger.debug(
                    "Quote enrichment skipped",
                    ticker=symbol,
                    error=str(enrich_exc),
                )

        from app.services.market_data.license import stamp_quote

        quote["symbol"] = symbol
        viewer = payload.get("user_id")
        if not isinstance(viewer, str) or not viewer.strip():
            viewer = email
        return sanitize_for_json(stamp_quote(quote, viewer_user_id=viewer.strip()))
    except Exception as exc:
        logger.warning("Quote fetch failed", ticker=symbol, error=str(exc))
        raise HTTPException(status_code=503, detail=f"Quote unavailable: {exc}")


@market_router.get("/search")
async def search_instrument_universe(
    q: str = Query("", max_length=80, description="Ticker or name fragment; empty = browse catalog"),
    limit: int = Query(24, ge=1, le=50),
    category: str = Query("all", description="equities | etf | crypto | fx | all"),
    region: str = Query("all", description="us | europe | asia | moex | fx | all"),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Search the full Marketstack universe plus local executable venues.

    Watchlist pins are annotated, never used as the search corpus.
    """
    from app.services.market_data.universe_search import search_universe
    from app.services.settings.watchlist import get_effective_watchlist

    pinned = await get_effective_watchlist(db, email)
    hits = await search_universe(
        q,
        limit=limit,
        category=category,
        region=region,
        pinned_symbols=pinned,
    )
    return sanitize_for_json(
        {
            "query": q.strip(),
            "category": category,
            "region": region,
            "watchlist_is_pins_only": True,
            "items": [h.as_dict() for h in hits],
        }
    )


@market_router.get("/fundamentals/{ticker}")
async def get_fundamentals_snapshot(
    ticker: str,
    email: str = Depends(get_current_user_email),
) -> dict:
    """FMP Key Metrics + Ratios single-glance snapshot."""
    from app.services.market_data.koyfin_snapshot import fetch_fmp_fundamentals_snapshot

    data = await fetch_fmp_fundamentals_snapshot(ticker)
    return sanitize_for_json(data)


@market_router.get("/watchlist-columns")
async def get_watchlist_columns(
    symbols: str = Query(..., description="Comma-separated tickers"),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Price + FMP fundamentals + Twelve Data / local technicals for watchlist columns."""
    import asyncio

    from app.services.market_data.client import get_latest_quote_resolved
    from app.services.market_data.koyfin_snapshot import (
        fetch_fmp_fundamentals_snapshot,
        fetch_twelve_data_technicals,
    )
    from app.services.market_data.quote_utils import enrich_quote_fields, extract_quote_price

    raw = [part.strip().upper() for part in symbols.split(",") if part.strip()]
    uniq: list[str] = []
    seen: set[str] = set()
    for sym in raw[:40]:
        if sym not in seen:
            seen.add(sym)
            uniq.append(sym)

    async def _row(sym: str) -> dict:
        quote: dict = {}
        fundamentals: dict = {}
        technicals: dict = {}
        try:
            quote = await get_latest_quote_resolved(sym)
            quote = enrich_quote_fields(dict(quote), None)
        except Exception as exc:
            logger.debug("Watchlist quote skipped", ticker=sym, error=str(exc))
        try:
            fundamentals = await fetch_fmp_fundamentals_snapshot(sym)
        except Exception as exc:
            logger.debug("Watchlist FMP skipped", ticker=sym, error=str(exc))
        try:
            technicals = await fetch_twelve_data_technicals(sym)
        except Exception as exc:
            logger.debug("Watchlist Twelve Data skipped", ticker=sym, error=str(exc))
        if not technicals.get("rsi"):
            try:
                from datetime import datetime, timedelta, timezone

                from app.services.market_data.client import get_bars_resolved
                from app.services.market_data.name_card import _rsi14

                end = datetime.now(timezone.utc)
                bars = await get_bars_resolved(sym, "1d", end - timedelta(days=80), end)
                closes = [float(b["close"]) for b in bars if b.get("close") is not None]
                rsi = _rsi14(closes)
                if rsi is not None:
                    technicals = {**technicals, "rsi": rsi, "source": technicals.get("source") or "local_bars"}
            except Exception as exc:
                logger.debug("Watchlist local RSI skipped", ticker=sym, error=str(exc)[:120])
        price = extract_quote_price(quote)
        return {
            "symbol": sym,
            "price": price,
            "change_pct": quote.get("change_pct"),
            "pe_ratio": fundamentals.get("pe_ratio"),
            "price_to_book": fundamentals.get("price_to_book"),
            "market_cap": fundamentals.get("market_cap"),
            "beta": fundamentals.get("beta"),
            "rsi": technicals.get("rsi"),
            "sma20": technicals.get("sma20"),
            "fundamentals_source": fundamentals.get("source"),
            "technicals_source": technicals.get("source"),
        }

    rows = await asyncio.gather(*[_row(sym) for sym in uniq])
    return sanitize_for_json({"items": list(rows), "count": len(rows)})


@market_router.get("/screener")
async def get_stock_screener(
    marketCapMoreThan: int | None = Query(None),
    marketCapLowerThan: int | None = Query(None),
    priceMoreThan: float | None = Query(None),
    priceLowerThan: float | None = Query(None),
    betaMoreThan: float | None = Query(None),
    betaLowerThan: float | None = Query(None),
    volumeMoreThan: int | None = Query(None),
    peMoreThan: float | None = Query(None),
    peLowerThan: float | None = Query(None),
    dividendMoreThan: float | None = Query(None),
    volMoreThan: float | None = Query(None),
    volLowerThan: float | None = Query(None),
    esMoreThan: float | None = Query(None),
    esLowerThan: float | None = Query(None),
    sector: str | None = Query(None),
    industry: str | None = Query(None),
    exchange: str | None = Query(None),
    country: str | None = Query(None),
    isEtf: bool | None = Query(None),
    isActivelyTrading: bool | None = Query(True),
    limit: int = Query(50, ge=1, le=100),
    email: str = Depends(get_current_user_email),
) -> dict:
    """Catalog screener (Prompt 43); FMP only fills when catalog has no rows."""
    from app.services.screener.service import screen_live as catalog_screen

    filters = {
        "marketCapMoreThan": marketCapMoreThan,
        "marketCapLowerThan": marketCapLowerThan,
        "priceMoreThan": priceMoreThan,
        "priceLowerThan": priceLowerThan,
        "betaMoreThan": betaMoreThan,
        "betaLowerThan": betaLowerThan,
        "volumeMoreThan": volumeMoreThan,
        "peMoreThan": peMoreThan,
        "peLowerThan": peLowerThan,
        "dividendMoreThan": dividendMoreThan,
        "volMoreThan": volMoreThan,
        "volLowerThan": volLowerThan,
        "esMoreThan": esMoreThan,
        "esLowerThan": esLowerThan,
        "sector": sector,
        "industry": industry,
        "exchange": exchange,
        "country": country,
        "isEtf": isEtf,
        "isActivelyTrading": isActivelyTrading,
        "limit": limit,
    }
    catalog = await catalog_screen(filters)
    if catalog["items"]:
        return sanitize_for_json(catalog)
    from app.services.market_data.koyfin_snapshot import fetch_fmp_screener

    items = await fetch_fmp_screener(filters, limit=limit)
    source = "fmp"
    priced = sum(1 for it in items if isinstance(it.get("price"), (int, float)))
    if not items or priced < max(3, len(items) // 4):
        from app.services.market_data.market_overview import fetch_free_screener

        free = await fetch_free_screener(limit=limit)
        if not items:
            items = free
            source = "free_quotes"
        else:
            by_sym = {
                str(r.get("symbol") or "").upper(): r
                for r in free
                if isinstance(r.get("price"), (int, float))
            }
            for row in items:
                sym = str(row.get("symbol") or "").upper()
                fill = by_sym.get(sym)
                if not fill:
                    continue
                if not isinstance(row.get("price"), (int, float)):
                    row["price"] = fill.get("price")
                if row.get("sector") in (None, "", "—") and fill.get("sector"):
                    row["sector"] = fill.get("sector")
                row.setdefault("source", fill.get("source") or "free_quotes")
            source = "fmp+free_quotes"
    return sanitize_for_json({"items": items, "count": len(items), "source": source})


class _SavedScreenIn(BaseModel):
    name: str = "экран"
    filters: dict = Field(default_factory=dict)


@market_router.get("/screener/saved")
async def list_screener_saved(
    email: str = Depends(get_current_user_email),
) -> dict:
    from app.services.screener.service import list_saved

    return {"items": list_saved(email)}


@market_router.post("/screener/saved")
async def save_screener_screen(
    body: _SavedScreenIn,
    email: str = Depends(get_current_user_email),
) -> dict:
    from app.services.screener.service import save_screen

    return save_screen(email, body.name, body.filters)


@market_router.get("/screener/export")
async def export_screener(
    country: str | None = Query(None),
    sector: str | None = Query(None),
    betaMoreThan: float | None = Query(None),
    esMoreThan: float | None = Query(None),
    limit: int = Query(50, ge=1, le=300),
    email: str = Depends(get_current_user_email),
) -> Response:
    from app.services.screener.service import export_csv, screen_live

    payload = await screen_live(
        {"country": country, "sector": sector, "betaMoreThan": betaMoreThan, "esMoreThan": esMoreThan, "limit": limit}
    )
    return Response(content=export_csv(payload["items"]), media_type="text/csv")


# тФАтФА Backtesting тФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФА

backtest_router = APIRouter(prefix="/backtest", tags=["backtesting"])


@backtest_router.post("/run", response_model=BacktestResultOut, status_code=202)
async def run_backtest(
    body: BacktestRequest,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> BacktestResultOut:
    """Trigger a backtest run. Processing is async via Celery."""
    raise_if_ui_removed("backtest")
    run = BacktestRun(
        strategy=body.strategy,
        ticker=body.ticker.upper(),
        start_date=datetime.fromisoformat(body.start_date),
        end_date=datetime.fromisoformat(body.end_date),
        initial_capital=body.initial_capital,
        parameters=body.parameters,
        status="pending",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    try:
        from app.tasks.backtest import run_backtest_task
        run_backtest_task.delay(run_id=run.id)
    except Exception as exc:
        logger.error("Failed to queue backtest", error=str(exc))

    return BacktestResultOut.model_validate(run)


@backtest_router.get("/runs", response_model=list[BacktestResultOut])
async def list_backtest_runs(
    limit: int = Query(100, ge=1, le=500),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> list[BacktestResultOut]:
    """List recent backtest runs."""
    raise_if_ui_removed("backtest")
    from app.services.backtest_analysis.weekly import WEEKLY_ANALYSIS_STRATEGY, is_real_backtest_run

    result = await db.execute(
        select(BacktestRun)
        .where(BacktestRun.strategy != WEEKLY_ANALYSIS_STRATEGY)
        .order_by(desc(BacktestRun.created_at))
        .limit(limit)
    )
    runs = [r for r in result.scalars().all() if is_real_backtest_run(r)]
    return [BacktestResultOut.model_validate(r) for r in runs]


@backtest_router.get("/reports/weekly", response_model=list[BacktestResultOut])
async def list_weekly_analysis_reports(
    limit: int = Query(12, ge=1, le=52),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> list[BacktestResultOut]:
    """List persisted weekly backtest analysis reports."""
    raise_if_ui_removed("backtest")
    result = await db.execute(
        select(BacktestRun)
        .where(BacktestRun.strategy == "weekly_analysis")
        .order_by(desc(BacktestRun.created_at))
        .limit(limit)
    )
    return [BacktestResultOut.model_validate(r) for r in result.scalars().all()]


@backtest_router.get("/runs/{run_id}", response_model=BacktestResultOut)
async def get_backtest_run(
    run_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> BacktestResultOut:
    raise_if_ui_removed("backtest")
    result = await db.execute(select(BacktestRun).where(BacktestRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    return BacktestResultOut.model_validate(run)


# тФАтФА Audit Log тФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФАтФА

audit_router = APIRouter(prefix="/audit", tags=["audit"])


@audit_router.get("/logs", response_model=PaginatedResponse)
async def list_audit_logs(
    action: Optional[str] = Query(None),
    action_prefix: Optional[str] = Query(None, description="Filter actions starting with prefix"),
    resource_type: Optional[str] = Query(None),
    resource_id: Optional[str] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse:
    """List audit logs with filtering and efficient pagination."""
    raise_if_ui_removed("audit_log")
    from sqlalchemy import func

    query = select(AuditLog).order_by(desc(AuditLog.timestamp))
    if action:
        query = query.where(AuditLog.action == action)
    elif action_prefix:
        query = query.where(AuditLog.action.like(f"{action_prefix}%"))
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
    if resource_id:
        query = query.where(AuditLog.resource_id == resource_id)
    if start_time:
        query = query.where(AuditLog.timestamp >= start_time)
    if end_time:
        query = query.where(AuditLog.timestamp <= end_time)

    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()

    offset = (page - 1) * page_size
    result = await db.execute(query.offset(offset).limit(page_size))
    logs = result.scalars().all()

    return PaginatedResponse(
        items=[AuditLogOut.model_validate(l) for l in logs],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, (total + page_size - 1) // page_size),
    )


@audit_router.get("/trail/{resource_type}/{resource_id}", response_model=list[AuditLogOut])
async def get_audit_trail(
    resource_type: str,
    resource_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> list[AuditLogOut]:
    """Per-resource audit trail."""
    raise_if_ui_removed("audit_log")
    result = await db.execute(
        select(AuditLog)
        .where(
            AuditLog.resource_type == resource_type,
            AuditLog.resource_id == resource_id,
        )
        .order_by(desc(AuditLog.timestamp))
        .limit(200)
    )
    return [AuditLogOut.model_validate(l) for l in result.scalars().all()]
