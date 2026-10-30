"""Equity analytics module — separate from crypto analytics (Prompt 10)."""
from __future__ import annotations

from typing import Any

from app.services.equity.intent_enrichment import enrich_intent_with_event_proximity
from app.services.equity.proximity import EventProximityResult, compute_event_proximity_risk

__all__ = [
    "EquityAnalyticsService",
    "EventProximityResult",
    "compute_event_proximity_risk",
    "enrich_intent_with_event_proximity",
    "get_equity_analytics_service",
    "ingest_equity_analytics",
    "ingest_symbol_equity_data",
]


def __getattr__(name: str) -> Any:
    if name in {"EquityAnalyticsService", "get_equity_analytics_service"}:
        from app.services.equity.analytics import EquityAnalyticsService, get_equity_analytics_service

        return EquityAnalyticsService if name == "EquityAnalyticsService" else get_equity_analytics_service
    if name in {"ingest_equity_analytics", "ingest_symbol_equity_data"}:
        from app.services.equity.ingestion import ingest_equity_analytics, ingest_symbol_equity_data

        return ingest_equity_analytics if name == "ingest_equity_analytics" else ingest_symbol_equity_data
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
