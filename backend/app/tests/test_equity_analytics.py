"""Tests for event_proximity_risk calculation (Prompt 10)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.deal_intent_enums import RiskTag
from app.services.equity.intent_enrichment import enrich_intent_with_event_proximity
from app.services.equity.proximity import ProximityEventType, compute_event_proximity_risk
from app.tests.test_domain_deal_intent import _sample_intent


def _dt(days_offset: float = 0.0) -> datetime:
    base = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    return base + timedelta(days=days_offset)


class TestEventProximityRisk:
    def test_no_events_not_at_risk(self):
        result = compute_event_proximity_risk(_dt(), [], [])
        assert result.is_at_risk is False
        assert result.event_type == ProximityEventType.NONE
        assert result.days_to_nearest_event is None

    def test_earnings_within_default_window(self):
        result = compute_event_proximity_risk(_dt(), [_dt(3)], [], earnings_window_days=5)
        assert result.is_at_risk is True
        assert result.event_type == ProximityEventType.EARNINGS
        assert result.earnings_within_window is True
        assert result.days_to_nearest_event == pytest.approx(3.0)

    def test_earnings_outside_window(self):
        result = compute_event_proximity_risk(_dt(), [_dt(10)], [], earnings_window_days=5)
        assert result.is_at_risk is False
        assert result.event_type == ProximityEventType.NONE

    def test_dividend_within_window(self):
        result = compute_event_proximity_risk(_dt(), [], [_dt(2)], dividend_window_days=3)
        assert result.is_at_risk is True
        assert result.event_type == ProximityEventType.DIVIDEND
        assert result.dividend_within_window is True

    def test_both_events_within_windows(self):
        result = compute_event_proximity_risk(
            _dt(),
            [_dt(4)],
            [_dt(2)],
            earnings_window_days=5,
            dividend_window_days=3,
        )
        assert result.is_at_risk is True
        assert result.event_type == ProximityEventType.BOTH
        assert result.earnings_within_window is True
        assert result.dividend_within_window is True

    def test_past_earnings_within_window_counts(self):
        result = compute_event_proximity_risk(_dt(), [_dt(-2)], [], earnings_window_days=5)
        assert result.is_at_risk is True
        assert result.days_to_nearest_event == pytest.approx(2.0)

    def test_custom_windows(self):
        result = compute_event_proximity_risk(
            _dt(),
            [_dt(7)],
            [_dt(6)],
            earnings_window_days=7,
            dividend_window_days=6,
        )
        assert result.is_at_risk is True
        assert result.event_type == ProximityEventType.BOTH

    def test_nearest_event_selected(self):
        result = compute_event_proximity_risk(_dt(), [_dt(8), _dt(2), _dt(15)], [], earnings_window_days=5)
        assert result.is_at_risk is True
        assert result.days_to_nearest_event == pytest.approx(2.0)


class TestIntentEnrichment:
    def test_enrichment_sets_event_risk_and_news_lock(self):
        intent = _sample_intent()
        proximity = compute_event_proximity_risk(_dt(), [_dt(1)], [])
        enriched = enrich_intent_with_event_proximity(intent, proximity)
        assert enriched.risk_tag == RiskTag.EVENT_RISK
        assert enriched.news_lock is True

    def test_no_enrichment_when_not_at_risk(self):
        intent = _sample_intent()
        proximity = compute_event_proximity_risk(_dt(), [_dt(30)], [])
        enriched = enrich_intent_with_event_proximity(intent, proximity)
        assert enriched.risk_tag == intent.risk_tag
        assert enriched.news_lock is intent.news_lock
