"""Equity analytics read-model schemas (Prompt 10)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class EventProximityOut(BaseModel):
    is_at_risk: bool
    event_type: str
    days_to_nearest_event: Optional[float] = None
    nearest_event_at: Optional[datetime] = None
    earnings_within_window: bool = False
    dividend_within_window: bool = False
    reason: str


class MarketSessionProfileOut(BaseModel):
    session_type: str
    avg_return_pct: float
    avg_volume_ratio: float
    volatility: float


class LiquidityFilterOut(BaseModel):
    min_volume_threshold: int
    avg_volume_20d: int
    passes_filter: bool


class VolatilityByRegimeOut(BaseModel):
    regime: str
    realized_vol: float


class NewsImpactScoreOut(BaseModel):
    score: float
    article_count: int
    nearest_event_hours: Optional[float] = None


class SectorRotationScoreOut(BaseModel):
    sector: str
    score: float
    as_of_date: str


class EquityAnalyticsOut(BaseModel):
    """Aggregate equity analytics read model for Asset Cockpit and Event Risk Layer."""

    symbol: str
    event_proximity: EventProximityOut
    liquidity_filter: Optional[LiquidityFilterOut] = None
    news_impact: Optional[NewsImpactScoreOut] = None
    session_profiles: list[MarketSessionProfileOut] = Field(default_factory=list)
    volatility_by_regime: list[VolatilityByRegimeOut] = Field(default_factory=list)
    sector_rotation: Optional[SectorRotationScoreOut] = None
    upcoming_earnings: list[dict[str, Any]] = Field(default_factory=list)
    upcoming_dividends: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
