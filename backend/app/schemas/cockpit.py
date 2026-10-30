"""Asset Cockpit aggregate read-model schemas (Prompt 9)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.schemas.equity import EquityAnalyticsOut
from app.schemas.schemas import AuditLogOut, NewsArticleOut


class CockpitPriceRange(BaseModel):
    period_low: float
    period_high: float
    range_pct: float


class CockpitVolatilityBands(BaseModel):
    mid: float
    upper: float
    lower: float
    realized_vol: float


class CockpitCorrelationPeer(BaseModel):
    symbol: str
    correlation: float
    relation: str


class CockpitIntentSummary(BaseModel):
    id: str
    status: str
    strategy: str
    direction: str
    risk_tag: str
    approval_state: str
    created_at: datetime


class CockpitSleeveBudget(BaseModel):
    sleeve_id: str
    sleeve_name: str
    risk_budget: float
    risk_used: float
    risk_remaining: float
    status: str


class CockpitMacroEvent(BaseModel):
    id: str
    title: str
    event_type: str
    scheduled_at: Optional[datetime] = None
    source: str = "stub"
    is_stub: bool = True


class CockpitDecisionExplanation(BaseModel):
    decision_type: str
    summary: str
    text: str
    timestamp: Optional[datetime] = None
    source_metrics: dict[str, Any] = Field(default_factory=dict)


class CockpitExplainabilityOut(BaseModel):
    headline: str
    regime_explanation: Optional[str] = None
    factor_explanation: Optional[str] = None
    forecast_explanation: Optional[str] = None
    risk_explanation: Optional[str] = None
    recent_decisions: list[CockpitDecisionExplanation] = Field(default_factory=list)
    source_metrics: dict[str, Any] = Field(default_factory=dict)


class AssetCockpitOut(BaseModel):
    symbol: str
    instrument_id: Optional[int] = None
    category: Optional[str] = None
    tradable_unit: str = "per_share"
    price: Optional[float] = None
    change_pct: Optional[float] = None
    quote_source: Optional[str] = None
    regime: str = "unknown"
    regime_label: str = "UNKNOWN"

    price_range: CockpitPriceRange
    volatility_bands: CockpitVolatilityBands

    liquidity_state: str
    spread_state: str
    spread_bps: float

    sector: Optional[str] = None
    sector_relation: str
    correlations: list[CockpitCorrelationPeer] = Field(default_factory=list)

    bot_suitability_score: int = Field(ge=0, le=100)
    allowed_strategies: list[str] = Field(default_factory=list)

    intents: list[CockpitIntentSummary] = Field(default_factory=list)
    sleeve_budget: Optional[CockpitSleeveBudget] = None

    news: list[NewsArticleOut] = Field(default_factory=list)
    macro_events: list[CockpitMacroEvent] = Field(default_factory=list)
    recent_actions: list[AuditLogOut] = Field(default_factory=list)

    equity_analytics: Optional[EquityAnalyticsOut] = None
    why_so: Optional[CockpitExplainabilityOut] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
