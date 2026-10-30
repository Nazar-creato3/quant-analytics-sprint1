"""Build MarketContext from profile, sleeve, and data-layer read models."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NewsArticle
from app.domain.deal_intent import DealIntentRead
from app.domain.enums import AssetCategory
from app.domain.instrument import InstrumentORM
from app.domain.market_data import MarketOhlcvORM
from app.domain.profile import ProfileRead
from app.domain.sleeve import SleeveRead
from app.services.approval.models import MarketContext
from app.services.event_risk import get_event_risk_layer
from app.services.liquidity import get_liquidity_monitor
from app.services.sleeve import IntentRiskRequest, SleeveEngine, SleevePositionSnapshot

NEWS_LOCK_SENTIMENT_THRESHOLD = -0.5
NEWS_LOCK_LOOKBACK_HOURS = 24
_VOLATILITY_BAR_LIMIT = 30


def realized_volatility(closes: list[float]) -> float:
    """Normalized realized volatility from close prices."""
    if len(closes) < 2:
        return 0.0
    returns: list[float] = []
    for index in range(1, len(closes)):
        previous, current = closes[index - 1], closes[index]
        if previous <= 0:
            continue
        returns.append((current - previous) / previous)
    if not returns:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / len(returns)
    return min(1.0, max(0.0, variance**0.5 * (252**0.5)))


def spread_bps(high: float, low: float, close: float) -> float:
    """Estimate bid-ask spread in bps from the latest bar range."""
    if close <= 0:
        return 0.0
    return max(0.0, (high - low) / close * 10_000)


class MarketContextBuilder:
    """Assemble approval inputs from instruments, OHLCV, news, and sleeve state."""

    def __init__(
        self,
        *,
        total_capital_usd: Decimal | float = Decimal("100000"),
        event_risk_layer=None,
        liquidity_monitor=None,
    ) -> None:
        self._sleeve_engine = SleeveEngine(total_capital_usd=total_capital_usd)
        self._event_risk_layer = event_risk_layer or get_event_risk_layer()
        self._liquidity_monitor = liquidity_monitor or get_liquidity_monitor()

    async def build(
        self,
        db: AsyncSession,
        *,
        intent: DealIntentRead,
        profile: ProfileRead,
        sleeve: SleeveRead,
        positions: list[SleevePositionSnapshot] | None = None,
        pending_intents: list[IntentRiskRequest] | None = None,
        max_correlation_with_portfolio: float = 0.0,
        market_regime: str = "unknown",
        profile_drawdown_pct: float = 0.0,
        profile_daily_loss_abs: Decimal | None = None,
    ) -> MarketContext:
        instrument = await self._load_instrument(db, intent.instrument_id)
        category = (
            AssetCategory(instrument.category)
            if instrument is not None and instrument.category
            else None
        )
        symbol = instrument.symbol if instrument is not None else ""

        volatility, estimated_spread = await self._market_microstructure(db, intent.instrument_id)
        news_locked = await self._news_locked_instrument_ids(db, symbol, intent.instrument_id)
        active_lock_instruments = await self._event_risk_layer.locked_instrument_ids(db)
        active_lock_sleeves = await self._event_risk_layer.locked_sleeve_ids(db)
        liquidity_drought_locked = await self._liquidity_monitor.locked_instrument_ids(db)
        active_lock_instruments = frozenset(
            set(active_lock_instruments) | set(liquidity_drought_locked)
        )
        event_locked = await self._event_proximity_locked(db, symbol, intent.instrument_id, category)
        news_locked = frozenset(set(news_locked) | set(event_locked))

        session_prefs = profile.session_preferences or {}
        session_killed = bool(session_prefs.get("session_killed", False))
        freeze_ids = session_prefs.get("freeze_sleeve_ids") or {}

        risk_used = self._sleeve_engine.risk_usage_by_sleeve(
            positions or (),
            pending_intents or (),
        ).get(sleeve.id, Decimal("0"))
        risk_remaining = sleeve.risk_budget - risk_used

        return MarketContext(
            instrument_volatility=volatility,
            instrument_spread_bps=estimated_spread,
            instrument_category=category,
            max_correlation_with_portfolio=max_correlation_with_portfolio,
            news_locked_instrument_ids=news_locked,
            event_proximity_locked_instrument_ids=event_locked,
            liquidity_drought_instrument_ids=liquidity_drought_locked,
            active_lock_instrument_ids=active_lock_instruments,
            active_lock_sleeve_ids=active_lock_sleeves,
            market_regime=market_regime,
            session_killed=session_killed,
            profile_drawdown_pct=profile_drawdown_pct,
            profile_daily_loss_abs=profile_daily_loss_abs or Decimal("0"),
            sleeve_status=sleeve.status,
            sleeve_risk_budget_remaining=risk_remaining,
            freeze_sleeve_requested=bool(freeze_ids.get(sleeve.id)),
        )

    async def _load_instrument(
        self,
        db: AsyncSession,
        instrument_id: int,
    ) -> InstrumentORM | None:
        result = await db.execute(
            select(InstrumentORM).where(InstrumentORM.id == instrument_id)
        )
        return result.scalar_one_or_none()

    async def _market_microstructure(
        self,
        db: AsyncSession,
        instrument_id: int,
    ) -> tuple[float, float]:
        result = await db.execute(
            select(MarketOhlcvORM)
            .where(MarketOhlcvORM.instrument_id == instrument_id)
            .order_by(desc(MarketOhlcvORM.time))
            .limit(_VOLATILITY_BAR_LIMIT)
        )
        bars = list(result.scalars().all())
        if not bars:
            return 0.0, 0.0

        bars.reverse()
        closes = [float(bar.close) for bar in bars if bar.close is not None]
        volatility = realized_volatility(closes)

        latest = bars[-1]
        if latest.high is None or latest.low is None or latest.close is None:
            return volatility, 0.0
        return volatility, spread_bps(float(latest.high), float(latest.low), float(latest.close))

    async def _news_locked_instrument_ids(
        self,
        db: AsyncSession,
        symbol: str,
        instrument_id: int,
    ) -> frozenset[int]:
        if not symbol:
            return frozenset()

        cutoff = datetime.now(timezone.utc) - timedelta(hours=NEWS_LOCK_LOOKBACK_HOURS)
        result = await db.execute(
            select(NewsArticle).where(NewsArticle.published_at >= cutoff)
        )
        locked: set[int] = set()
        symbol_upper = symbol.upper()
        for article in result.scalars().all():
            tickers = [value.upper() for value in (article.tickers_mentioned or [])]
            if symbol_upper not in tickers:
                continue
            sentiment = article.sentiment_score
            if sentiment is not None and sentiment <= NEWS_LOCK_SENTIMENT_THRESHOLD:
                locked.add(instrument_id)
        return frozenset(locked)

    async def _event_proximity_locked(
        self,
        db: AsyncSession,
        symbol: str,
        instrument_id: int,
        category: AssetCategory | None,
    ) -> frozenset[int]:
        if not symbol or category not in {AssetCategory.EQUITIES, AssetCategory.ETF, None}:
            return frozenset()
        if symbol.endswith("-USD"):
            return frozenset()

        from app.services.equity.analytics import get_equity_analytics_service

        proximity = await get_equity_analytics_service().compute_proximity(db, symbol)
        if proximity.is_at_risk:
            return frozenset({instrument_id})
        return frozenset()
