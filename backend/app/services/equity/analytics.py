"""Equity analytics computation and read-model assembly."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import NewsArticle
from app.domain.equity import (
    DividendEventORM,
    EarningsCalendarORM,
    LiquidityFilterORM,
    MarketSessionProfileORM,
    NewsImpactScoreORM,
    SectorRotationScoreORM,
    VolatilityByRegimeORM,
)
from app.domain.instrument import InstrumentORM
from app.schemas.equity import (
    EquityAnalyticsOut,
    EventProximityOut,
    LiquidityFilterOut,
    MarketSessionProfileOut,
    NewsImpactScoreOut,
    SectorRotationScoreOut,
    VolatilityByRegimeOut,
)
from app.services.equity.proximity import (
    EventProximityResult,
    compute_event_proximity_risk,
    proximity_window_end,
)
from app.services.market_regime.service import label_from_closes


def compute_news_impact_score(
    articles: list[Any],
    *,
    as_of: datetime,
    nearest_event_at: datetime | None = None,
    lookback_hours: int = 72,
) -> tuple[float, int, float | None]:
    """Blend sentiment magnitude with time decay; boost when near corporate events."""
    cutoff = as_of - timedelta(hours=lookback_hours)
    weighted_sum = 0.0
    weight_total = 0.0
    count = 0

    for article in articles:
        published = article.published_at
        if published is None:
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        if published < cutoff:
            continue
        sentiment = article.sentiment_score
        if sentiment is None:
            continue
        hours_ago = max(0.0, (as_of - published).total_seconds() / 3600)
        decay = math.exp(-hours_ago / 24.0)
        weighted_sum += float(sentiment) * decay
        weight_total += decay
        count += 1

    base_score = weighted_sum / weight_total if weight_total > 0 else 0.0

    nearest_event_hours: float | None = None
    if nearest_event_at is not None:
        nearest = nearest_event_at if nearest_event_at.tzinfo else nearest_event_at.replace(tzinfo=timezone.utc)
        nearest_event_hours = (nearest - as_of).total_seconds() / 3600
        if abs(nearest_event_hours) <= 72:
            proximity_boost = max(0.0, 1.0 - abs(nearest_event_hours) / 72.0)
            sign = -1.0 if base_score < 0 else 1.0
            base_score = max(-1.0, min(1.0, base_score + sign * proximity_boost * 0.25))

    return round(base_score, 4), count, nearest_event_hours


def compute_liquidity_filter(avg_volume_20d: float, *, min_volume: int | None = None) -> LiquidityFilterOut:
    threshold = min_volume or settings.EQUITY_MIN_VOLUME_THRESHOLD
    avg_int = int(avg_volume_20d)
    return LiquidityFilterOut(
        min_volume_threshold=threshold,
        avg_volume_20d=avg_int,
        passes_filter=avg_int >= threshold,
    )


def compute_session_profiles(bars: list[Any]) -> list[MarketSessionProfileOut]:
    """Estimate pre/regular/after-hours behavior from daily bars (proxy when intraday unavailable)."""
    if len(bars) < 5:
        return [
            MarketSessionProfileOut(
                session_type="regular",
                avg_return_pct=0.0,
                avg_volume_ratio=1.0,
                volatility=0.0,
            )
        ]

    returns: list[float] = []
    volumes: list[float] = []
    for bar in bars[-20:]:
        if bar.open and bar.close:
            returns.append((float(bar.close) - float(bar.open)) / float(bar.open) * 100)
        if bar.volume:
            volumes.append(float(bar.volume))

    avg_return = sum(returns) / len(returns) if returns else 0.0
    avg_vol = sum(volumes) / len(volumes) if volumes else 0.0
    vol_std = (
        math.sqrt(sum((value - avg_return) ** 2 for value in returns) / len(returns))
        if len(returns) > 1
        else 0.0
    )

    return [
        MarketSessionProfileOut(
            session_type="pre_market",
            avg_return_pct=round(avg_return * 0.35, 4),
            avg_volume_ratio=round(0.18, 4),
            volatility=round(vol_std * 1.2, 4),
        ),
        MarketSessionProfileOut(
            session_type="regular",
            avg_return_pct=round(avg_return, 4),
            avg_volume_ratio=round(1.0, 4),
            volatility=round(vol_std, 4),
        ),
        MarketSessionProfileOut(
            session_type="after_hours",
            avg_return_pct=round(avg_return * 0.25, 4),
            avg_volume_ratio=round(0.12, 4),
            volatility=round(vol_std * 1.15, 4),
        ),
    ]


def compute_volatility_by_regime(bars: list[Any]) -> list[VolatilityByRegimeOut]:
    if len(bars) < 10:
        return []

    df = pd.DataFrame(
        {
            "open": [float(b.open) for b in bars],
            "high": [float(b.high) for b in bars],
            "low": [float(b.low) for b in bars],
            "close": [float(b.close) for b in bars],
            "volume": [float(b.volume) for b in bars],
        }
    )
    regime = label_from_closes(df["close"].tolist(), ticker="equity")
    closes = df["close"].tolist()
    returns = [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1] > 0
    ]
    realized = math.sqrt(sum(r * r for r in returns) / len(returns)) * math.sqrt(252) if returns else 0.0
    return [VolatilityByRegimeOut(regime=regime, realized_vol=round(realized, 4))]


class EquityAnalyticsService:
    """Build equity analytics read models from DB + bar history."""

    async def load_event_dates(
        self,
        db: AsyncSession,
        symbol: str,
        *,
        as_of: datetime | None = None,
    ) -> tuple[list[datetime], list[datetime]]:
        now = as_of or datetime.now(timezone.utc)
        window_end = proximity_window_end(
            now,
            earnings_window_days=settings.EQUITY_EARNINGS_PROXIMITY_DAYS,
            dividend_window_days=settings.EQUITY_DIVIDEND_PROXIMITY_DAYS,
        )
        lookback = now - timedelta(days=settings.EQUITY_EARNINGS_PROXIMITY_DAYS)

        earnings_result = await db.execute(
            select(EarningsCalendarORM.report_date)
            .where(
                EarningsCalendarORM.symbol == symbol.upper(),
                EarningsCalendarORM.report_date >= lookback,
                EarningsCalendarORM.report_date <= window_end,
            )
            .order_by(EarningsCalendarORM.report_date)
        )
        dividend_result = await db.execute(
            select(DividendEventORM.ex_dividend_date)
            .where(
                DividendEventORM.symbol == symbol.upper(),
                DividendEventORM.ex_dividend_date >= lookback,
                DividendEventORM.ex_dividend_date <= window_end,
            )
            .order_by(DividendEventORM.ex_dividend_date)
        )
        earnings = list(earnings_result.scalars().all())
        dividends = list(dividend_result.scalars().all())
        return earnings, dividends

    async def compute_proximity(
        self,
        db: AsyncSession,
        symbol: str,
        *,
        as_of: datetime | None = None,
    ) -> EventProximityResult:
        earnings, dividends = await self.load_event_dates(db, symbol, as_of=as_of)
        return compute_event_proximity_risk(
            as_of or datetime.now(timezone.utc),
            earnings,
            dividends,
            earnings_window_days=settings.EQUITY_EARNINGS_PROXIMITY_DAYS,
            dividend_window_days=settings.EQUITY_DIVIDEND_PROXIMITY_DAYS,
        )

    async def build(
        self,
        db: AsyncSession,
        symbol: str,
        *,
        bars: list[Any] | None = None,
        sector: str | None = None,
        instrument_id: int | None = None,
    ) -> EquityAnalyticsOut:
        symbol = symbol.strip().upper()
        as_of = datetime.now(timezone.utc)
        proximity = await self.compute_proximity(db, symbol, as_of=as_of)

        avg_volume = 0.0
        if bars:
            avg_volume = sum(float(b.volume) for b in bars[-20:]) / max(1, min(len(bars), 20))
        liquidity = compute_liquidity_filter(avg_volume)

        articles = await self._load_news(db, symbol)
        news_score, article_count, nearest_hours = compute_news_impact_score(
            articles,
            as_of=as_of,
            nearest_event_at=proximity.nearest_event_at,
        )

        session_profiles = compute_session_profiles(bars or [])
        vol_by_regime = compute_volatility_by_regime(bars or [])
        sector_rotation = await self._load_sector_rotation(db, sector)
        upcoming_earnings = await self._load_upcoming_earnings(db, symbol)
        upcoming_dividends = await self._load_upcoming_dividends(db, symbol)

        return EquityAnalyticsOut(
            symbol=symbol,
            event_proximity=EventProximityOut(
                is_at_risk=proximity.is_at_risk,
                event_type=proximity.event_type.value,
                days_to_nearest_event=proximity.days_to_nearest_event,
                nearest_event_at=proximity.nearest_event_at,
                earnings_within_window=proximity.earnings_within_window,
                dividend_within_window=proximity.dividend_within_window,
                reason=proximity.reason,
            ),
            liquidity_filter=liquidity,
            news_impact=NewsImpactScoreOut(
                score=news_score,
                article_count=article_count,
                nearest_event_hours=nearest_hours,
            ),
            session_profiles=session_profiles,
            volatility_by_regime=vol_by_regime,
            sector_rotation=sector_rotation,
            upcoming_earnings=upcoming_earnings,
            upcoming_dividends=upcoming_dividends,
            metadata={
                "instrument_id": instrument_id,
                "computed_at": as_of.isoformat(),
            },
        )

    async def _load_news(self, db: AsyncSession, symbol: str) -> list[NewsArticle]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.NEWS_LOOKBACK_HOURS)
        result = await db.execute(
            select(NewsArticle).where(NewsArticle.published_at >= cutoff).limit(200)
        )
        symbol_upper = symbol.upper()
        return [
            row
            for row in result.scalars().all()
            if symbol_upper in [value.upper() for value in (row.tickers_mentioned or [])]
        ]

    async def _load_sector_rotation(
        self,
        db: AsyncSession,
        sector: str | None,
    ) -> SectorRotationScoreOut | None:
        if not sector:
            return None
        result = await db.execute(
            select(SectorRotationScoreORM)
            .where(SectorRotationScoreORM.sector == sector)
            .order_by(desc(SectorRotationScoreORM.as_of_date))
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return SectorRotationScoreOut(
            sector=row.sector,
            score=row.score,
            as_of_date=row.as_of_date.isoformat(),
        )

    async def _load_upcoming_earnings(self, db: AsyncSession, symbol: str) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=settings.INVESTING_EVENTS_LOOKAHEAD_DAYS)
        result = await db.execute(
            select(EarningsCalendarORM)
            .where(
                EarningsCalendarORM.symbol == symbol.upper(),
                EarningsCalendarORM.report_date >= now - timedelta(days=1),
                EarningsCalendarORM.report_date <= end,
            )
            .order_by(EarningsCalendarORM.report_date)
            .limit(5)
        )
        return [
            {
                "report_date": row.report_date.isoformat(),
                "fiscal_period": row.fiscal_period,
                "eps_estimate": float(row.eps_estimate) if row.eps_estimate is not None else None,
                "source": row.source,
            }
            for row in result.scalars().all()
        ]

    async def _load_upcoming_dividends(self, db: AsyncSession, symbol: str) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=settings.INVESTING_EVENTS_LOOKAHEAD_DAYS)
        result = await db.execute(
            select(DividendEventORM)
            .where(
                DividendEventORM.symbol == symbol.upper(),
                DividendEventORM.ex_dividend_date >= now - timedelta(days=1),
                DividendEventORM.ex_dividend_date <= end,
            )
            .order_by(DividendEventORM.ex_dividend_date)
            .limit(5)
        )
        return [
            {
                "ex_dividend_date": row.ex_dividend_date.isoformat(),
                "amount": float(row.amount),
                "currency": row.currency,
                "source": row.source,
            }
            for row in result.scalars().all()
        ]

    async def resolve_instrument_id(
        self,
        db: AsyncSession,
        symbol: str,
    ) -> int | None:
        result = await db.execute(
            select(InstrumentORM.id)
            .where(InstrumentORM.symbol == symbol.upper())
            .order_by(desc(InstrumentORM.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()


_equity_service = EquityAnalyticsService()


def get_equity_analytics_service() -> EquityAnalyticsService:
    return _equity_service
