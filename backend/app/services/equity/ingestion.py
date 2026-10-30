"""Persist equity calendar and corporate action data."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.equity import (
    CorporateActionORM,
    DividendEventORM,
    EarningsCalendarORM,
    LiquidityFilterORM,
    MarketSessionProfileORM,
    NewsImpactScoreORM,
    SectorRotationScoreORM,
    SplitHistoryORM,
    VolatilityByRegimeORM,
)
from app.domain.instrument import InstrumentORM
from app.services.data import investing_rapidapi
from app.services.equity.analytics import (
    EquityAnalyticsService,
    compute_liquidity_filter,
    compute_news_impact_score,
    compute_session_profiles,
    compute_volatility_by_regime,
)
from app.services.equity.client import fetch_equity_fundamentals
from app.services.macro.client import _parse_dt

logger = get_logger(__name__)


async def _resolve_instrument_id(db: AsyncSession, symbol: str) -> int | None:
    result = await db.execute(
        select(InstrumentORM.id).where(InstrumentORM.symbol == symbol.upper()).limit(1)
    )
    return result.scalar_one_or_none()


async def store_earnings_row(
    db: AsyncSession,
    *,
    symbol: str,
    report_date: datetime,
    instrument_id: int | None,
    fiscal_period: str | None = None,
    eps_estimate: Decimal | None = None,
    source: str,
    raw_data: dict[str, Any] | None = None,
) -> EarningsCalendarORM:
    existing = await db.execute(
        select(EarningsCalendarORM).where(
            EarningsCalendarORM.symbol == symbol.upper(),
            EarningsCalendarORM.report_date == report_date,
            EarningsCalendarORM.source == source,
        )
    )
    row = existing.scalar_one_or_none()
    if row is None:
        row = EarningsCalendarORM(
            symbol=symbol.upper(),
            instrument_id=instrument_id,
            report_date=report_date,
            fiscal_period=fiscal_period,
            eps_estimate=eps_estimate,
            source=source,
            raw_data=raw_data or {},
        )
        db.add(row)
    else:
        row.instrument_id = instrument_id or row.instrument_id
        row.fiscal_period = fiscal_period or row.fiscal_period
        row.eps_estimate = eps_estimate if eps_estimate is not None else row.eps_estimate
        row.raw_data = raw_data or row.raw_data
    return row


async def ingest_symbol_equity_data(db: AsyncSession, symbol: str) -> dict[str, int]:
    """Ingest yfinance fundamentals + optional RapidAPI earnings for one symbol."""
    symbol = symbol.upper()
    instrument_id = await _resolve_instrument_id(db, symbol)
    counts = {"earnings": 0, "dividends": 0, "splits": 0, "corporate_actions": 0}

    yf_data = await fetch_equity_fundamentals(symbol)
    for item in yf_data.get("earnings", []):
        await store_earnings_row(
            db,
            symbol=symbol,
            report_date=item["report_date"],
            instrument_id=instrument_id,
            source=item.get("source", "yfinance"),
            raw_data=item.get("raw_data"),
        )
        counts["earnings"] += 1

    for item in yf_data.get("dividends", []):
        db.add(
            DividendEventORM(
                symbol=symbol,
                instrument_id=instrument_id,
                ex_dividend_date=item["ex_dividend_date"],
                amount=item["amount"],
                currency=item.get("currency", "USD"),
                source=item.get("source", "yfinance"),
            )
        )
        counts["dividends"] += 1
        db.add(
            CorporateActionORM(
                symbol=symbol,
                instrument_id=instrument_id,
                action_type="dividend",
                effective_date=item["ex_dividend_date"],
                details={"amount": str(item["amount"]), "currency": item.get("currency", "USD")},
                source=item.get("source", "yfinance"),
            )
        )
        counts["corporate_actions"] += 1

    for item in yf_data.get("splits", []):
        db.add(
            SplitHistoryORM(
                symbol=symbol,
                instrument_id=instrument_id,
                split_date=item["split_date"],
                ratio=item["ratio"],
                source=item.get("source", "yfinance"),
            )
        )
        counts["splits"] += 1
        db.add(
            CorporateActionORM(
                symbol=symbol,
                instrument_id=instrument_id,
                action_type="split",
                effective_date=item["split_date"],
                details={"ratio": str(item["ratio"])},
                source=item.get("source", "yfinance"),
            )
        )
        counts["corporate_actions"] += 1

    if investing_rapidapi.is_configured():
        earnings = await investing_rapidapi.fetch_earnings()
        for ev in earnings:
            tickers = [value.upper() for value in (ev.get("tickers_affected") or [])]
            if symbol not in tickers:
                continue
            report_date = _parse_dt(ev.get("event_date"))
            if report_date is None:
                continue
            eps_raw = ev.get("eps_estimate")
            eps_estimate = None
            if eps_raw is not None:
                try:
                    eps_estimate = Decimal(str(eps_raw))
                except Exception:
                    eps_estimate = None
            await store_earnings_row(
                db,
                symbol=symbol,
                report_date=report_date,
                instrument_id=instrument_id,
                eps_estimate=eps_estimate,
                source=ev.get("source", "investing_rapidapi"),
                raw_data=ev,
            )
            counts["earnings"] += 1

    return counts


async def refresh_computed_snapshots(
    db: AsyncSession,
    symbol: str,
    *,
    bars: list[Any] | None = None,
    sector: str | None = None,
) -> None:
    """Persist derived analytics snapshots for cockpit / event risk layer."""
    symbol = symbol.upper()
    instrument_id = await _resolve_instrument_id(db, symbol)
    as_of = datetime.now(timezone.utc)

    avg_volume = 0.0
    if bars:
        avg_volume = sum(float(b.volume) for b in bars[-20:]) / max(1, min(len(bars), 20))
    liquidity = compute_liquidity_filter(avg_volume)
    db.add(
        LiquidityFilterORM(
            symbol=symbol,
            instrument_id=instrument_id,
            min_volume_threshold=liquidity.min_volume_threshold,
            avg_volume_20d=liquidity.avg_volume_20d,
            passes_filter=liquidity.passes_filter,
            computed_at=as_of,
        )
    )

    for profile in compute_session_profiles(bars or []):
        db.add(
            MarketSessionProfileORM(
                symbol=symbol,
                instrument_id=instrument_id,
                session_type=profile.session_type,
                avg_return_pct=profile.avg_return_pct,
                avg_volume_ratio=profile.avg_volume_ratio,
                volatility=profile.volatility,
                computed_at=as_of,
            )
        )

    for item in compute_volatility_by_regime(bars or []):
        db.add(
            VolatilityByRegimeORM(
                symbol=symbol,
                instrument_id=instrument_id,
                regime=item.regime,
                realized_vol=item.realized_vol,
                computed_at=as_of,
            )
        )

    service = EquityAnalyticsService()
    proximity = await service.compute_proximity(db, symbol, as_of=as_of)
    articles = await service._load_news(db, symbol)
    score, article_count, nearest_hours = compute_news_impact_score(
        articles,
        as_of=as_of,
        nearest_event_at=proximity.nearest_event_at,
    )
    db.add(
        NewsImpactScoreORM(
            symbol=symbol,
            instrument_id=instrument_id,
            score=score,
            article_count=article_count,
            nearest_event_hours=nearest_hours,
            computed_at=as_of,
        )
    )

    if sector:
        score_val = 50.0
        if bars and len(bars) >= 20:
            first_close = float(bars[-20].close)
            last_close = float(bars[-1].close)
            if first_close > 0:
                score_val = max(0.0, min(100.0, (last_close / first_close - 1) * 100 + 50))
        db.add(
            SectorRotationScoreORM(
                sector=sector,
                as_of_date=date.today(),
                score=round(score_val, 4),
                metadata_={"symbol": symbol},
            )
        )


async def ingest_equity_analytics(
    db: AsyncSession,
    symbols: list[str],
    *,
    bars_by_symbol: dict[str, list[Any]] | None = None,
    sectors_by_symbol: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    totals = {"earnings": 0, "dividends": 0, "splits": 0, "corporate_actions": 0, "symbols": 0}
    for symbol in symbols:
        try:
            counts = await ingest_symbol_equity_data(db, symbol)
            for key in ("earnings", "dividends", "splits", "corporate_actions"):
                totals[key] += counts.get(key, 0)
            await refresh_computed_snapshots(
                db,
                symbol,
                bars=(bars_by_symbol or {}).get(symbol.upper()),
                sector=(sectors_by_symbol or {}).get(symbol.upper()),
            )
            totals["symbols"] += 1
        except Exception as exc:
            logger.warning("Equity analytics ingest failed", symbol=symbol, error=str(exc))
    await db.commit()
    return totals
