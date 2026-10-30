from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)

_EMPTY_DATA_STATUS = "degraded"
_SUCCESS_STATUS = "success"
_FAILED_STATUS = "failed"


def _run_async(coro):
    return run_async(coro)


@celery_app.task(name="app.tasks.data_ingestion.ingest_market_data_task")
def ingest_market_data_task(
    tickers: list[str] | None = None,
    days_back: int = 365,
) -> dict[str, Any]:
    from app.core.config import settings
    from app.utils.healthchecks import ping_healthcheck

    tickers_list = tickers or settings.default_watchlist_list
    try:
        result = _run_async(_async_ingest_bars(tickers_list, days_back))
        ping_healthcheck(settings.HC_PING_DATA_INGESTION, success=result.get("status") != _FAILED_STATUS)
        return result
    except Exception as exc:
        logger.exception("Market data ingestion task failed", error=str(exc))
        ping_healthcheck(settings.HC_PING_DATA_INGESTION, success=False)
        return {
            "status": _FAILED_STATUS,
            "inserted": 0,
            "errors": 1,
            "tickers": len(tickers_list),
            "reason": str(exc),
        }


async def _async_ingest_bars(tickers: list[str], days_back: int) -> dict[str, Any]:
    from sqlalchemy.dialects.postgresql import insert
    from app.db.models import OHLCVBar
    from app.db.session import AsyncSessionLocal
    from app.services.market_data.binance_spot import get_crypto_bars, is_crypto_ticker
    from app.services.market_data.client import get_market_data_client

    client = get_market_data_client()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days_back)
    inserted = 0
    errors = 0
    empty_tickers: list[str] = []

    async with AsyncSessionLocal() as session:
        for ticker in tickers:
            try:
                if is_crypto_ticker(ticker):
                    bars = await get_crypto_bars(ticker, "1d", min(days_back, 400))
                else:
                    bars = await client.get_bars(ticker, "1d", start, end)
                if not bars:
                    empty_tickers.append(ticker)
                    logger.warning("No bars returned", ticker=ticker)
                    continue

                for bar in bars:
                    ts_raw = bar.get("timestamp")
                    ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")) if isinstance(ts_raw, str) else ts_raw
                    stmt = (
                        insert(OHLCVBar)
                        .values(
                            ticker=ticker,
                            timestamp=ts,
                            timeframe="1d",
                            open=bar["open"],
                            high=bar["high"],
                            low=bar["low"],
                            close=bar["close"],
                            volume=bar["volume"],
                            vwap=bar.get("vwap"),
                            trade_count=bar.get("trade_count"),
                            source=settings.MARKET_DATA_PROVIDER.value,
                        )
                        .on_conflict_do_nothing(constraint="uq_ohlcv_bar")
                    )
                    await session.execute(stmt)
                    inserted += 1

                await session.commit()
                logger.debug("Bars ingested", ticker=ticker, count=len(bars))
            except Exception as exc:
                errors += 1
                await session.rollback()
                logger.warning("Bar ingest failed", ticker=ticker, error=str(exc))

    status = _SUCCESS_STATUS if inserted > 0 and errors == 0 else _EMPTY_DATA_STATUS if inserted == 0 and errors == 0 else _FAILED_STATUS
    logger.info("Bar ingestion complete", status=status, inserted=inserted, errors=errors, empty_tickers=len(empty_tickers))
    return {
        "status": status,
        "inserted": inserted,
        "errors": errors,
        "tickers": len(tickers),
        "empty_tickers": empty_tickers,
    }


@celery_app.task(name="app.tasks.data_ingestion.ingest_news_task")
def ingest_news_task(tickers: list[str] | None = None) -> dict[str, Any]:
    tickers_list = tickers or settings.default_watchlist_list
    try:
        result = _run_async(_async_ingest_news(tickers_list))
        return result
    except Exception as exc:
        logger.exception("News ingestion task failed", error=str(exc))
        return {
            "status": _FAILED_STATUS,
            "articles": 0,
            "tickers": len(tickers_list),
            "reason": str(exc),
        }


async def _async_ingest_news(tickers: list[str]) -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.news.client import fetch_and_store_news, fetch_and_store_rss_news

    async with AsyncSessionLocal() as session:
        from app.services.news.license import source_catalog

        logger.info("news_source_catalog", sources=source_catalog())
        articles = await fetch_and_store_news(tickers, db_session=session)
        if not articles:
            articles = await fetch_and_store_rss_news(db_session=session)

    articles_count = len(articles) if articles is not None else 0
    status = _SUCCESS_STATUS if articles_count > 0 else _EMPTY_DATA_STATUS
    try:
        from app.services.terminal_platform.market.news_fetch import fetch_terminal_news_multi

        await fetch_terminal_news_multi(limit=20, force_refresh=True)
    except Exception as exc:
        logger.warning("terminal news cache warm failed after ingest", error=str(exc))
    logger.info("News ingestion complete", status=status, articles=articles_count)
    return {"status": status, "articles": articles_count, "tickers": len(tickers)}


@celery_app.task(name="app.tasks.data_ingestion.ingest_macro_events_task")
def ingest_macro_events_task() -> dict[str, Any]:
    try:
        return _run_async(_async_ingest_macro())
    except Exception as exc:
        logger.exception("Macro ingestion task failed", error=str(exc))
        return {"status": _FAILED_STATUS, "events": 0, "reason": str(exc)}


async def _async_ingest_macro() -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.macro.client import fetch_and_store_macro_events

    async with AsyncSessionLocal() as session:
        events = await fetch_and_store_macro_events(session)

    events_count = len(events) if events is not None else 0
    status = _SUCCESS_STATUS if events_count > 0 else _EMPTY_DATA_STATUS
    logger.info("Macro ingestion complete", status=status, events=events_count)
    return {"status": status, "events": events_count}


@celery_app.task(name="app.tasks.data_ingestion.ingest_macro_indicators_task")
def ingest_macro_indicators_task(*, lookback_days: int = 365) -> dict[str, Any]:
    try:
        return _run_async(_async_ingest_macro_indicators(lookback_days))
    except Exception as exc:
        logger.exception("Macro indicators ingestion task failed", error=str(exc))
        return {"status": _FAILED_STATUS, "fetched": 0, "stored": 0, "reason": str(exc)}


async def _async_ingest_macro_indicators(lookback_days: int) -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.macro.indicators import fetch_and_store_macro_indicators
    from app.services.macro.sector_seed import seed_sector_mapping

    async with AsyncSessionLocal() as session:
        result = await fetch_and_store_macro_indicators(session, lookback_days=lookback_days)
        sector_result = await seed_sector_mapping(session)

    status = _SUCCESS_STATUS if result.get("stored", 0) > 0 else _EMPTY_DATA_STATUS
    logger.info(
        "Macro indicators ingestion complete",
        status=status,
        fetched=result.get("fetched", 0),
        stored=result.get("stored", 0),
        sectors=sector_result.get("seeded", 0),
    )
    return {"status": status, **result, "sector_seed": sector_result}


@celery_app.task(name="app.tasks.data_ingestion.ingest_investing_intel_task")
def ingest_investing_intel_task(symbols: list[str] | None = None) -> dict[str, Any]:
    tickers_list = symbols or settings.default_watchlist_list
    try:
        return _run_async(_async_ingest_investing(tickers_list))
    except Exception as exc:
        logger.exception("Investing intel task failed", error=str(exc))
        return {
            "status": _FAILED_STATUS,
            "configured": False,
            "events": 0,
            "earnings": 0,
            "quotes": 0,
            "stored": 0,
            "reason": str(exc),
        }


def _event_measures(ev: dict[str, Any]) -> tuple[float, float] | None:
    """Real effect and confidence, or nothing. Missing values are not 0 and 0.5."""
    effect = ev.get("market_effect")
    confidence = ev.get("confidence")
    if effect in (None, "") or confidence in (None, ""):
        return None
    try:
        return float(effect), float(confidence)
    except (TypeError, ValueError):
        return None


async def _async_ingest_investing(symbols: list[str]) -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.db.models import MacroEvent
    from app.services.data import investing_rapidapi
    from app.services.macro.client import _parse_dt

    if not investing_rapidapi.is_configured():
        logger.info("Investing RapidAPI not configured, skipping intel ingestion")
        return {"status": _EMPTY_DATA_STATUS, "configured": False, "events": 0, "earnings": 0, "quotes": 0, "stored": 0}

    intel = await investing_rapidapi.fetch_market_intelligence(symbols)
    combined = list(intel.get("events", [])) + list(intel.get("earnings", []))

    stored = 0
    if combined:
        async with AsyncSessionLocal() as session:
            for ev in combined:
                try:
                    measures = _event_measures(ev)
                    if measures is None:
                        logger.info("investing event skipped: no effect", name=ev.get("event_name"))
                        continue
                    effect, confidence = measures
                    session.add(
                        MacroEvent(
                            event_name=ev.get("event_name", "investing event"),
                            event_date=_parse_dt(ev.get("event_date")),
                            country=ev.get("country", "GLOBAL"),
                            impact=ev.get("impact", "medium"),
                            source=ev.get("source", "investing_rapidapi"),
                            source_url=ev.get("source_url"),
                            market_effect=effect,
                            confidence=confidence,
                            tickers_affected=ev.get("tickers_affected", []),
                            raw_data=ev,
                        )
                    )
                    stored += 1
                except Exception as exc:
                    logger.warning("Investing event store failed", error=str(exc))
            await session.commit()

    events_count = len(intel.get("events", []))
    earnings_count = len(intel.get("earnings", []))
    quotes_count = len(intel.get("quotes", {}))
    status = _SUCCESS_STATUS if stored > 0 else _EMPTY_DATA_STATUS
    logger.info(
        "Investing intel ingestion complete",
        status=status,
        events=events_count,
        earnings=earnings_count,
        quotes=quotes_count,
        stored=stored,
    )
    return {
        "status": status,
        "configured": True,
        "events": events_count,
        "earnings": earnings_count,
        "quotes": quotes_count,
        "stored": stored,
    }


@celery_app.task(name="app.tasks.data_ingestion.ingest_equity_analytics_task")
def ingest_equity_analytics_task(symbols: list[str] | None = None) -> dict[str, Any]:
    tickers_list = symbols or settings.default_watchlist_list
    try:
        return _run_async(_async_ingest_equity_analytics(tickers_list))
    except Exception as exc:
        logger.exception("Equity analytics ingestion task failed", error=str(exc))
        return {
            "status": _FAILED_STATUS,
            "symbols": len(tickers_list),
            "reason": str(exc),
        }


async def _async_ingest_equity_analytics(symbols: list[str]) -> dict[str, Any]:
    from app.db.session import AsyncSessionLocal
    from app.services.equity.ingestion import ingest_equity_analytics
    from app.services.market_data.bars import get_bars_for_chart

    equity_symbols = [symbol for symbol in symbols if not symbol.upper().endswith("-USD")]
    bars_by_symbol: dict[str, list[Any]] = {}
    sectors_by_symbol: dict[str, str | None] = {}

    async with AsyncSessionLocal() as session:
        for symbol in equity_symbols:
            try:
                bars = await get_bars_for_chart(session, symbol.upper(), "1d", 60)
                bars_by_symbol[symbol.upper()] = bars
            except Exception:
                bars_by_symbol[symbol.upper()] = []

        totals = await ingest_equity_analytics(
            session,
            equity_symbols,
            bars_by_symbol=bars_by_symbol,
            sectors_by_symbol=sectors_by_symbol,
        )

    status = _SUCCESS_STATUS if totals.get("symbols", 0) > 0 else _EMPTY_DATA_STATUS
    logger.info("Equity analytics ingestion complete", status=status, **totals)
    return {"status": status, **totals}