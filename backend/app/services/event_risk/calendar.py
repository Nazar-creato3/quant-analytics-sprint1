"""Earnings/macro calendar adapter for EventRiskLayer."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MacroEvent
from app.services.equity.proximity import EventProximityResult, ProximityEventType


class EventCalendarAdapter:
    """Calendar read model — EquityAnalytics when available, MacroEvent fallback."""

    def __init__(self, equity_service: object | None = None) -> None:
        self._equity = equity_service
        if self._equity is None:
            try:
                from app.services.equity.analytics import get_equity_analytics_service

                self._equity = get_equity_analytics_service()
            except ImportError:
                self._equity = None

    async def load_proximity(
        self,
        db: AsyncSession,
        symbol: str,
        *,
        as_of: datetime | None = None,
    ) -> EventProximityResult:
        if self._equity is None:
            return EventProximityResult(
                is_at_risk=False,
                event_type=ProximityEventType.NONE,
                days_to_nearest_event=None,
                nearest_event_at=None,
                earnings_within_window=False,
                dividend_within_window=False,
                reason="нет данных",
            )
        return await self._equity.compute_proximity(db, symbol, as_of=as_of)

    async def load_macro_events(
        self,
        db: AsyncSession,
        *,
        as_of: datetime | None = None,
        lookahead_hours: int = 48,
    ) -> list[MacroEvent]:
        now = as_of or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        end = now + timedelta(hours=lookahead_hours)
        lookback = now - timedelta(hours=24)
        result = await db.execute(
            select(MacroEvent)
            .where(MacroEvent.event_date >= lookback, MacroEvent.event_date <= end)
            .order_by(MacroEvent.event_date)
            .limit(200)
        )
        return list(result.scalars().all())
