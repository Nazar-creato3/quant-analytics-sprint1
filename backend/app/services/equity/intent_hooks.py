"""Async helpers to attach equity event tags before intent persistence."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.deal_intent import DealIntentCreate
from app.services.equity.analytics import get_equity_analytics_service
from app.services.equity.intent_enrichment import enrich_intent_with_event_proximity


async def enrich_intent_for_symbol(
    db: AsyncSession,
    symbol: str,
    intent: DealIntentCreate,
) -> DealIntentCreate:
    """Load proximity from DB and apply event_risk + news_lock when warranted."""
    proximity = await get_equity_analytics_service().compute_proximity(db, symbol)
    return enrich_intent_with_event_proximity(intent, proximity)
