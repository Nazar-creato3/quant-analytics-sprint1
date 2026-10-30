"""Event risk layer value types."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class NewsShockTarget:
    """Instrument or sector subject to news_shock scoring."""

    symbol: str
    instrument_id: int | None = None
    sector: str | None = None
    sleeve_ids: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class NewsShockAssessment:
    """Computed news_shock score for a target."""

    target: NewsShockTarget
    score: float
    news_impact: float
    calendar_boost: float
    macro_boost: float
    article_count: int
    reason: str
    news_impact_probability: float = 0.0
    analog_probability: float = 0.0
    factor_alignment: float = 0.0
    daily_volatility: float = 0.0
    topic_tags: tuple[str, ...] = ()
    source_event_id: str | None = None
    triggered_at: datetime | None = None
