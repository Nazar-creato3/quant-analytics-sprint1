"""Tests for LiquidityMonitor — depth collapse, drought lock, and recovery."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.domain.active_lock import ActiveLockCreate, ActiveLockORM, ActiveLockType
from app.domain.deal_intent_enums import RiskTag
from app.services.approval.engine import evaluate_policy
from app.services.approval.models import MarketContext, PolicyState
from app.services.event_risk.repository import ActiveLockRepository
from app.services.liquidity.monitor import LiquidityMonitor, resolve_liquidity_threshold
from app.services.liquidity.scoring import compute_liquidity_score
from app.tests.test_approval_policy_engine import _context, _intent, _profile


def _depth_levels(qty: float, *, levels: int = 5, start_price: float = 100.0) -> tuple[list[dict], list[dict]]:
    bids = [{"price": str(start_price - index * 0.1), "qty": str(qty)} for index in range(levels)]
    asks = [{"price": str(start_price + 0.1 + index * 0.1), "qty": str(qty)} for index in range(levels)]
    return bids, asks


def _snapshot(
    *,
    bid_qty: float,
    ask_qty: float | None = None,
    spread_bps: float = 5.0,
    instrument_id: int = 101,
) -> SimpleNamespace:
    bids, asks = _depth_levels(bid_qty)
    if ask_qty is not None:
        _, asks = _depth_levels(ask_qty)
    return SimpleNamespace(
        time=datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc),
        instrument_id=instrument_id,
        bid_depth=bids,
        ask_depth=asks,
        spread_bps=Decimal(str(spread_bps)),
    )


def _query_result(*, rows=None, scalar=None, rowcount: int | None = None):
    result = MagicMock()
    if rowcount is not None:
        result.rowcount = rowcount
    scalars = MagicMock()
    scalars.all.return_value = rows or []
    result.scalars.return_value = scalars
    result.scalar_one_or_none.return_value = scalar
    return result


class TestLiquidityScoring:
    def test_deep_book_scores_high(self):
        baseline_bids, baseline_asks = _depth_levels(10.0)
        current_bids, current_asks = _depth_levels(12.0)
        score = compute_liquidity_score(
            spread_bps=5.0,
            bid_depth=current_bids,
            ask_depth=current_asks,
            baseline_bid_depth=baseline_bids,
            baseline_ask_depth=baseline_asks,
            volume_ratio=1.2,
            depth_levels=5,
            max_spread_bps=100.0,
        )
        assert score >= 0.8

    def test_collapsed_depth_scores_low(self):
        baseline_bids, baseline_asks = _depth_levels(10.0)
        current_bids, current_asks = _depth_levels(0.2)
        score = compute_liquidity_score(
            spread_bps=80.0,
            bid_depth=current_bids,
            ask_depth=current_asks,
            baseline_bid_depth=baseline_bids,
            baseline_ask_depth=baseline_asks,
            volume_ratio=0.1,
            depth_levels=5,
            max_spread_bps=100.0,
        )
        assert score < 0.35


class TestLiquidityMonitorCycle:
    @pytest.mark.asyncio
    async def test_depth_collapse_triggers_drought_lock(self):
        settings = Settings(
            LIQUIDITY_DROUGHT_THRESHOLD=0.35,
            LIQUIDITY_DROUGHT_LOCK_TTL_MINUTES=30,
            LIQUIDITY_DEPTH_LEVELS=5,
            LIQUIDITY_BASELINE_SNAPSHOTS=3,
            LIQUIDITY_VOLUME_LOOKBACK_BARS=5,
        )
        repo = ActiveLockRepository()
        monitor = LiquidityMonitor(settings=settings, repository=repo)
        db = AsyncMock()

        instrument = SimpleNamespace(id=101, symbol="BTCUSDT")
        deep_snapshot = _snapshot(bid_qty=10.0, ask_qty=10.0, spread_bps=5.0)
        thin_snapshot = _snapshot(bid_qty=0.1, ask_qty=0.1, spread_bps=90.0)
        volume_bars = [
            SimpleNamespace(volume=Decimal("100")),
            SimpleNamespace(volume=Decimal("100")),
            SimpleNamespace(volume=Decimal("100")),
            SimpleNamespace(volume=Decimal("100")),
            SimpleNamespace(volume=Decimal("10")),
        ]

        async def execute_side_effect(statement):
            sql = str(statement)
            if "DELETE" in sql:
                return _query_result(rowcount=0)
            if "order_book_snapshots" in sql:
                return _query_result(rows=[thin_snapshot, deep_snapshot, deep_snapshot, deep_snapshot])
            if "ohlcv" in sql:
                return _query_result(rows=volume_bars)
            if "instruments" in sql:
                return _query_result(rows=[instrument])
            if "active_locks" in sql:
                return _query_result(scalar=None, rows=[])
            return _query_result(rows=[])

        db.execute.side_effect = execute_side_effect
        created_payloads: list[ActiveLockCreate] = []

        async def create_side_effect(_db, payload: ActiveLockCreate):
            created_payloads.append(payload)
            return ActiveLockORM(
                id="lock-1",
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
        repo.release_locks = AsyncMock(return_value=0)

        result = await monitor.process_cycle(db, drought_threshold=0.35)

        assert result["triggered"] == 1
        assert len(created_payloads) == 1
        assert created_payloads[0].lock_type == ActiveLockType.LIQUIDITY_DROUGHT
        assert created_payloads[0].instrument_id == 101
        assert created_payloads[0].metadata["liquidity_score"] < 0.35

    @pytest.mark.asyncio
    async def test_depth_recovery_releases_drought_lock(self):
        settings = Settings(
            LIQUIDITY_DROUGHT_THRESHOLD=0.35,
            LIQUIDITY_DEPTH_LEVELS=5,
            LIQUIDITY_BASELINE_SNAPSHOTS=3,
            LIQUIDITY_VOLUME_LOOKBACK_BARS=5,
        )
        repo = ActiveLockRepository()
        monitor = LiquidityMonitor(settings=settings, repository=repo)
        db = AsyncMock()

        instrument = SimpleNamespace(id=101, symbol="BTCUSDT")
        deep_snapshot = _snapshot(bid_qty=10.0, ask_qty=10.0, spread_bps=5.0)
        volume_bars = [SimpleNamespace(volume=Decimal("100")) for _ in range(6)]

        async def execute_side_effect(statement):
            sql = str(statement)
            if "DELETE" in sql and "active_locks" in sql:
                return _query_result(rowcount=1)
            if "DELETE" in sql:
                return _query_result(rowcount=0)
            if "order_book_snapshots" in sql:
                return _query_result(rows=[deep_snapshot, deep_snapshot, deep_snapshot])
            if "ohlcv" in sql:
                return _query_result(rows=volume_bars)
            if "instruments" in sql:
                return _query_result(rows=[instrument])
            if "active_locks" in sql:
                return _query_result(scalar="lock-1", rows=[])
            return _query_result(rows=[])

        db.execute.side_effect = execute_side_effect
        repo.create = AsyncMock()
        repo.has_active_lock = AsyncMock(return_value=True)
        repo.release_locks = AsyncMock(return_value=1)

        result = await monitor.process_cycle(db, drought_threshold=0.35)

        assert result["released"] == 1
        repo.release_locks.assert_awaited_once()
        release_kwargs = repo.release_locks.await_args.kwargs
        assert release_kwargs["instrument_id"] == 101
        assert release_kwargs["lock_type"] == ActiveLockType.LIQUIDITY_DROUGHT


class TestLiquidityThreshold:
    def test_profile_override(self):
        settings = Settings(LIQUIDITY_DROUGHT_THRESHOLD=0.35)
        assert resolve_liquidity_threshold({"min_liquidity_score": 0.5}, settings) == 0.5
        assert resolve_liquidity_threshold({}, settings) == 0.35


class TestApprovalLiquidityDrought:
    def test_liquidity_drought_blocks_conditional_approve(self):
        decision = evaluate_policy(
            _intent(
                risk_tag=RiskTag.MEDIUM,
                required_confidence=0.85,
                approval_threshold=Decimal("0.95"),
                instrument_id=101,
            ),
            _profile(),
            _context(
                liquidity_drought_instrument_ids=frozenset({101}),
                active_lock_instrument_ids=frozenset({101}),
            ),
        )
        assert decision.state == PolicyState.HOLD_FOR_REVIEW
        assert decision.conditions_met is False
        assert any(
            "liquidity_drought" in failure
            for failure in (decision.metadata.get("failures") or [])
        )

    def test_no_drought_allows_conditional_approve(self):
        decision = evaluate_policy(
            _intent(
                risk_tag=RiskTag.MEDIUM,
                required_confidence=0.85,
                approval_threshold=Decimal("0.95"),
            ),
            _profile(),
            _context(
                liquidity_drought_instrument_ids=frozenset(),
                active_lock_instrument_ids=frozenset(),
            ),
        )
        assert decision.state == PolicyState.CONDITIONAL_APPROVE
