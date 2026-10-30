"""Orchestrate portfolio risk analytics: holdings → prices → snapshot."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.portfolio_risk import PortfolioRiskSnapshotORM
from app.services.instrument.resolver import resolve_or_create_instrument
from app.services.portfolio.holdings import current_book_holdings
from app.services.portfolio.risk_analytics_math import (
    LOOKBACK_TRADING_DAYS,
    HoldingSpec,
    PortfolioRiskReport,
    STRESS_SCENARIOS,
    build_report,
)
from app.utils.helpers import new_uuid

logger = get_logger(__name__)

def _bar_date(ts) -> str | None:
    if ts is None:
        return None
    if hasattr(ts, "date"):
        try:
            return ts.date().isoformat()
        except Exception as exc:
            logger.warning("bar date parse failed", error=str(exc)[:200])
    text = str(ts)
    return text[:10] if len(text) >= 10 else None


async def _closes_from_ohlcv(
    db: AsyncSession,
    instrument_id: int,
    *,
    start: datetime,
    end: datetime,
) -> list[tuple[str, float]]:
    from sqlalchemy import select

    from app.domain.market_data import MarketOhlcvORM

    stmt = (
        select(MarketOhlcvORM.time, MarketOhlcvORM.close)
        .where(
            MarketOhlcvORM.instrument_id == instrument_id,
            MarketOhlcvORM.timeframe == "1d",
            MarketOhlcvORM.time >= start,
            MarketOhlcvORM.time <= end,
            MarketOhlcvORM.close.is_not(None),
        )
        .order_by(MarketOhlcvORM.time.asc())
    )
    rows = (await db.execute(stmt)).all()
    out: list[tuple[str, float]] = []
    for ts, close in rows:
        day = _bar_date(ts)
        if day and close is not None:
            out.append((day, float(close)))
    return out


def _closes_from_price_store(symbol: str, *, start: datetime, end: datetime) -> list[tuple[str, float]]:
    try:
        from app.services.price_history import service as ph

        lo, hi = start.date(), end.date()
        return [(d.isoformat(), float(p)) for d, p in ph.closes(symbol) if lo <= d <= hi and p > 0]
    except Exception as exc:  # noqa: BLE001
        logger.debug("price store closes unavailable", symbol=symbol, error=str(exc))
        return []


async def load_dated_closes(
    db: AsyncSession,
    symbol: str,
    *,
    start: datetime,
    end: datetime,
) -> list[tuple[str, float]]:
    """Daily closes for risk windows — OHLCV first, then provider chain."""
    try:
        instrument = await resolve_or_create_instrument(db, symbol)
        cached = await _closes_from_ohlcv(db, instrument.id, start=start, end=end)
        # 40 bars used to be "enough" even when a 1-year window was asked for: a backtest
        # requested over 365 days ran on 59. Accept the DB only when it covers ~80% of the
        # window's trading days; otherwise fill from the local price-history store first.
        expected = max(40, int((end - start).days * 5 / 7 * 0.8))
        if len(cached) >= expected:
            return cached
        stored = _closes_from_price_store(symbol, start=start, end=end)
        if len(stored) > len(cached):
            merged = {d: p for d, p in stored}
            merged.update({d: p for d, p in cached})
            cached = sorted(merged.items())
        if len(cached) >= 40:
            # Best local history; the provider is asked only when there is almost nothing.
            return cached
    except Exception as exc:
        logger.debug("instrument resolve failed", symbol=symbol, error=str(exc))
        cached = []

    try:
        from app.services.market_data.client import get_bars_resolved

        bars = await get_bars_resolved(symbol, "1d", start, end)
    except Exception as exc:
        logger.debug("dated closes provider failed", symbol=symbol, error=str(exc))
        bars = []

    out: list[tuple[str, float]] = list(cached)
    seen = {d for d, _ in out}
    for bar in bars or []:
        if isinstance(bar, dict):
            ts = bar.get("timestamp") or bar.get("time") or bar.get("date")
            close = bar.get("close")
        else:
            ts = getattr(bar, "timestamp", None)
            close = getattr(bar, "close", None)
        day = _bar_date(ts)
        if not day or close is None or day in seen:
            continue
        try:
            price = float(close)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        seen.add(day)
        out.append((day, price))
    out.sort(key=lambda row: row[0])
    return out


async def load_series_for_symbols(
    db: AsyncSession,
    symbols: Sequence[str],
    *,
    start: datetime,
    end: datetime,
) -> dict[str, list[tuple[str, float]]]:
    series: dict[str, list[tuple[str, float]]] = {}
    for symbol in symbols:
        series[symbol] = await load_dated_closes(db, symbol, start=start, end=end)
    return series


async def compute_portfolio_risk_report(
    db: AsyncSession,
    *,
    owner_user_id: str | None = None,
    owner_email: str | None = None,
    holdings: Sequence[HoldingSpec] | None = None,
    series_by_symbol: dict[str, list[tuple[str, float]]] | None = None,
    persist: bool = True,
    lookback_days: int = LOOKBACK_TRADING_DAYS,
    benchmark_symbol: str = "SPY",
) -> PortfolioRiskReport:
    """Build (and optionally persist) the institutional risk report."""
    book = None
    if holdings is None:
        book = await current_book_holdings(
            db, owner_user_id=owner_user_id, owner_email=owner_email
        )
        holdings = book.holdings
        owner_user_id = owner_user_id or book.owner_user_id

    now = datetime.now(timezone.utc)
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    # Need COVID window + 252d lookback; load from 2020-01-01 through today.
    needed = {h.symbol for h in holdings}
    needed.add(benchmark_symbol)

    if series_by_symbol is None:
        series_by_symbol = await load_series_for_symbols(db, sorted(needed), start=start, end=now)

    report = build_report(
        holdings=holdings,
        series_by_symbol=series_by_symbol,
        benchmark_symbol=benchmark_symbol,
        lookback_days=lookback_days,
        now=now,
    )

    if persist and owner_user_id and not report.insufficient_data:
        try:
            from datetime import date

            snapshot = PortfolioRiskSnapshotORM(
                id=new_uuid(),
                user_id=owner_user_id,
                computed_at=now,
                lookback_start=date.fromisoformat(report.lookback_start) if report.lookback_start else now.date(),
                lookback_end=date.fromisoformat(report.lookback_end) if report.lookback_end else now.date(),
                lookback_days=report.lookback_days,
                var_method="fhs_ewma",
                benchmark_symbol=report.benchmark_symbol,
                var_95=report.var_95,
                var_99=report.var_99,
                expected_shortfall_95=report.expected_shortfall_95,
                var_95_usd=report.var_95_usd,
                var_99_usd=report.var_99_usd,
                expected_shortfall_95_usd=report.expected_shortfall_95_usd,
                alpha=report.alpha,
                beta=report.beta,
                r_squared=report.r_squared,
                avg_pairwise_correlation=report.avg_pairwise_correlation,
                concentration_share=report.concentration_share,
                insufficient_data=report.insufficient_data,
                holdings=report.holdings,
                sector_weights=report.sector_weights,
                correlation_matrix={
                    "symbols": report.correlation_symbols,
                    "matrix": report.correlation_matrix,
                },
                methodology=report.methodology,
                payload=report.to_dict(),
                data_as_of=now,
                notes="; ".join(report.notes) if report.notes else None,
            )
            db.add(snapshot)
            await db.flush()
        except Exception as exc:
            logger.warning("risk snapshot persist skipped", error=str(exc))

    return report


def available_stress_scenarios() -> list[dict[str, str]]:
    return [
        {
            "id": s["id"],
            "label_ru": s["label_ru"],
            "start": s["start"],
            "end": s["end"],
            "description_ru": s["description_ru"],
        }
        for s in STRESS_SCENARIOS.values()
    ]
