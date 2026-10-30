"""Tests for EventRiskLayer — news_shock trigger and TTL expiry."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.domain.active_lock import ActiveLockCreate, ActiveLockORM, ActiveLockType
from app.domain.deal_intent_enums import RiskTag
from app.services.approval.engine import evaluate_policy
from app.services.approval.models import MarketContext, PolicyState
from app.services.event_risk.layer import EventRiskLayer
from app.services.event_risk.repository import ActiveLockRepository
from app.services.event_risk.scoring import compute_news_shock_score
from app.tests.test_approval_policy_engine import _context, _intent, _profile


def _article(*, sentiment: float, symbol: str = "AAPL", hours_ago: float = 1.0) -> SimpleNamespace:
    published = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return SimpleNamespace(
        published_at=published,
        sentiment_score=sentiment,
        tickers_mentioned=[symbol],
        title=f"{symbol} headline",
        description="",
    )


def _query_result(*, rows=None, scalar=None, rowcount: int | None = None):
    result = MagicMock()
    if rowcount is not None:
        result.rowcount = rowcount
    scalars = MagicMock()
    scalars.all.return_value = rows or []
    result.scalars.return_value = scalars
    mappings = MagicMock()
    mappings.all.return_value = rows or []
    result.mappings.return_value = mappings
    result.scalar_one_or_none.return_value = scalar
    return result


class TestNewsShockScoring:
    def test_negative_news_produces_shock(self):
        score, impact, calendar_boost, macro_boost, count, reason, probability = compute_news_shock_score(
            [_article(sentiment=-0.9)],
            as_of=datetime.now(timezone.utc),
        )
        assert score > 0.5
        assert impact < 0
        assert count == 1
        assert "negative news impact" in reason
        assert 0.0 <= probability.probability <= 1.0

    def test_positive_news_has_no_shock(self):
        score, _, calendar_boost, macro_boost, _, _, _ = compute_news_shock_score(
            [_article(sentiment=0.8)],
            as_of=datetime.now(timezone.utc),
        )
        assert score == 0.0
        assert calendar_boost == 0.0
        assert macro_boost == 0.0


class TestActiveLockRepository:
    @pytest.mark.asyncio
    async def test_expire_stale_unlocks(self):
        repo = ActiveLockRepository()
        db = AsyncMock()
        now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

        async def execute_side_effect(statement):
            sql = str(statement)
            if "DELETE" in sql:
                return _query_result(rowcount=1)
            return _query_result(rows=[102])

        db.execute.side_effect = execute_side_effect

        removed = await repo.expire_stale(db, as_of=now)
        assert removed == 1

        locked = await repo.locked_instrument_ids(db, as_of=now)
        assert 102 in locked
        assert 101 not in locked


class TestEventRiskLayerTrigger:
    @pytest.mark.asyncio
    async def test_threshold_breach_creates_lock_and_alert(self):
        settings = Settings(
            EVENT_RISK_NEWS_SHOCK_THRESHOLD=0.5,
            EVENT_RISK_LOCK_TTL_MINUTES=30,
            EVENT_RISK_POLL_LOOKBACK_MINUTES=120,
            NEWS_LOOKBACK_HOURS=72,
        )
        repo = ActiveLockRepository()
        layer = EventRiskLayer(settings=settings, repository=repo)
        db = AsyncMock()

        instrument = SimpleNamespace(id=101, symbol="AAPL", category="equities", metadata_={"sector": "Technology"})
        negative_article = _article(sentiment=-0.95, symbol="AAPL")

        async def execute_side_effect(statement):
            sql = str(statement)
            if "DELETE" in sql:
                return _query_result(rowcount=0)
            if "FROM news" in sql:
                return _query_result(rows=[])
            if "news_articles" in sql:
                return _query_result(rows=[negative_article])
            if "instruments" in sql:
                return _query_result(rows=[instrument])
            if "sleeves" in sql:
                return _query_result(rows=[])
            if "macro_events" in sql or "earnings_calendar" in sql or "dividend_events" in sql:
                return _query_result(rows=[])
            if "active_locks" in sql:
                return _query_result(scalar=None, rows=[])
            return _query_result(rows=[])

        db.execute.side_effect = execute_side_effect
        created_payloads: list[ActiveLockCreate] = []

        async def create_side_effect(_db, payload: ActiveLockCreate):
            created_payloads.append(payload)
            return ActiveLockORM(
                id="lock-created",
                lock_type=payload.lock_type.value,
                instrument_id=payload.instrument_id,
                sleeve_id=payload.sleeve_id,
                sector=payload.sector,
                news_shock_score=payload.news_shock_score,
                reason=payload.reason,
                source_event_id=payload.source_event_id,
                expires_at=payload.expires_at,
                metadata_=payload.metadata,
                created_at=datetime.now(timezone.utc),
            )

        repo.create = AsyncMock(side_effect=create_side_effect)
        repo.has_active_lock = AsyncMock(return_value=False)

        async def fake_poll(_db, *, as_of):
            return [negative_article]

        proximity = SimpleNamespace(
            is_at_risk=False,
            nearest_event_at=None,
        )

        with patch.object(layer, "_poll_news_stream", side_effect=fake_poll):
            with patch.object(layer._calendar, "load_proximity", new=AsyncMock(return_value=proximity)):
                with patch.object(layer._calendar, "load_macro_events", new=AsyncMock(return_value=[])):
                    with patch("app.services.event_risk.layer.emit_news_shock_alert", new=AsyncMock()) as alert_mock:
                        triggered = await layer.process_cycle(db)

        assert len(triggered) == 1
        assert triggered[0].score >= settings.EVENT_RISK_NEWS_SHOCK_THRESHOLD
        assert any(payload.instrument_id == 101 for payload in created_payloads)
        alert_mock.assert_awaited_once()


class TestApprovalActiveLocks:
    def test_active_lock_blocks_conditional_approve(self):
        decision = evaluate_policy(
            _intent(
                risk_tag=RiskTag.MEDIUM,
                required_confidence=0.85,
                approval_threshold=Decimal("0.95"),
                instrument_id=101,
                sleeve_id="sleeve-1",
            ),
            _profile(),
            _context(
                active_lock_instrument_ids=frozenset({101}),
                active_lock_sleeve_ids=frozenset(),
            ),
        )
        assert decision.state == PolicyState.HOLD_FOR_REVIEW
        assert decision.conditions_met is False
        assert any("active_locks" in failure for failure in (decision.metadata.get("failures") or []))

    def test_expired_lock_allows_conditional_approve(self):
        decision = evaluate_policy(
            _intent(
                risk_tag=RiskTag.MEDIUM,
                required_confidence=0.85,
                approval_threshold=Decimal("0.95"),
            ),
            _profile(),
            _context(active_lock_instrument_ids=frozenset(), active_lock_sleeve_ids=frozenset()),
        )
        assert decision.state == PolicyState.CONDITIONAL_APPROVE

    @pytest.mark.asyncio
    async def test_ttl_expiry_clears_lock_lookup(self):
        repo = ActiveLockRepository()
        now = datetime(2026, 7, 18, 15, 0, tzinfo=timezone.utc)
        db = AsyncMock()

        async def execute_side_effect(statement):
            sql = str(statement)
            if "DELETE" in sql:
                return _query_result(rowcount=1)
            return _query_result(rows=[])

        db.execute.side_effect = execute_side_effect

        await repo.expire_stale(db, as_of=now)
        locked = await repo.locked_instrument_ids(db, as_of=now)
        assert locked == frozenset()

