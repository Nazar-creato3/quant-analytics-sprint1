"""Event Risk Layer — realtime news_shock scoring and TTL news locks."""
from __future__ import annotations

from app.services.event_risk.factor_exposure_reader import FactorExposureReader
from app.services.event_risk.feedback import NewsImpactFeedbackService
from app.services.event_risk.layer import EventRiskLayer, get_event_risk_layer
from app.services.event_risk.news_impact import (
    NewsImpactAnalog,
    NewsImpactProbabilityResult,
    compute_news_impact_probability,
)
from app.services.event_risk.news_impact_repository import NewsImpactHistoryRepository
from app.services.event_risk.scoring import compute_news_shock_score
from app.services.event_risk.types import NewsShockAssessment, NewsShockTarget

__all__ = [
    "EventRiskLayer",
    "FactorExposureReader",
    "NewsImpactAnalog",
    "NewsImpactFeedbackService",
    "NewsImpactHistoryRepository",
    "NewsImpactProbabilityResult",
    "NewsShockAssessment",
    "NewsShockTarget",
    "compute_news_impact_probability",
    "compute_news_shock_score",
    "get_event_risk_layer",
]
