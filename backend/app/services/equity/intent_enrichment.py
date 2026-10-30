"""Apply event proximity tags to draft DealIntents."""
from __future__ import annotations

from app.domain.deal_intent import DealIntentCreate
from app.domain.deal_intent_enums import RiskTag
from app.services.equity.proximity import EventProximityResult


def enrich_intent_with_event_proximity(
    intent: DealIntentCreate,
    proximity: EventProximityResult,
) -> DealIntentCreate:
    """Auto-set event_risk tag and news_lock when near earnings/dividend."""
    if not proximity.is_at_risk:
        return intent

    return intent.model_copy(
        update={
            "risk_tag": RiskTag.EVENT_RISK,
            "news_lock": True,
        }
    )
