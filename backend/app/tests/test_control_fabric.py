"""Tests for ControlFabric — RiskGate, KillSwitch, AuditJournal, ReplayEngine."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.deal_intent_enums import DealIntentStatus
from app.domain.enums import AssetCategory, SleeveStatus
from app.services.approval.models import PolicyState
from app.services.control_fabric import (
    AuditJournal,
    ControlFabric,
    ControlFabricAuditAction,
    KillSwitchScope,
    KillSwitchService,
    KillSwitchTrigger,
    OpenPositionExposure,
    ReplayEngine,
    ReplayIntentRecord,
    RiskGate,
    RiskGateOutcome,
    RiskSnapshot,
    compute_atr,
    volatility_scaled_position_size,
)
from app.services.regime import MarketRegimeLabel
from app.tests.test_approval_policy_engine import _context, _intent, _profile

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _sleeve(**overrides: object):
    defaults = {
        "id": "sleeve-1",
        "profile_id": "user-1",
        "name": "Core",
        "category": AssetCategory.EQUITIES,
        "capital_allocation_pct": Decimal("60"),
        "risk_budget": Decimal("10000"),
        "status": SleeveStatus.ACTIVE,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    from app.domain.sleeve import SleeveRead

    return SleeveRead(**defaults)


class TestRiskGateATR:
    def test_compute_atr_from_ohlc(self):
        highs = [102.0, 103.0, 104.0, 105.0, 106.0] * 4
        lows = [98.0, 99.0, 100.0, 101.0, 102.0] * 4
        closes = [100.0, 101.0, 102.0, 103.0, 104.0] * 4
        atr = compute_atr(highs, lows, closes)
        assert atr > 0

    def test_volatility_scaled_position_size_reduces_on_high_atr(self):
        result = volatility_scaled_position_size(
            base_size_usd=Decimal("1000"),
            atr=5.0,
            price=100.0,
            profile_volatility_tolerance=0.5,
        )
        assert result.adjusted_size_usd < result.base_size_usd
        assert result.scale_factor < 1.0


class TestRiskGateChecks:
    def test_blocks_correlation_above_threshold(self):
        gate = RiskGate()
        profile = _profile(
            diversification_policy={"max_correlation": 0.7, "max_correlation_cluster_pct": 100},
        )
        intent = _intent()
        context = _context(max_correlation_with_portfolio=0.85)
        positions = [
            OpenPositionExposure(
                instrument_id=202,
                sleeve_id="sleeve-1",
                market_value_usd=Decimal("5000"),
            )
        ]

        result = gate.check_intent(
            intent,
            profile,
            _sleeve(),
            context,
            open_positions=positions,
            instrument_correlations={202: 0.85},
        )

        assert result.allowed is False
        assert result.outcome == RiskGateOutcome.BLOCKED
        assert "correlation" in result.reason

    def test_critical_breach_on_profile_drawdown(self):
        gate = RiskGate()
        profile = _profile(max_drawdown_pct=Decimal("10"))
        snapshot = RiskSnapshot(profile_drawdown_pct=12.0)

        result = gate.check_intent(
            _intent(),
            profile,
            _sleeve(),
            _context(),
            snapshot=snapshot,
        )

        assert result.triggers_kill_switch is True
        assert result.outcome == RiskGateOutcome.BREACH_CRITICAL

    def test_critical_breach_on_profile_daily_loss(self):
        gate = RiskGate()
        profile = _profile(
            max_daily_loss_abs=Decimal("3000"),
            diversification_policy={"max_correlation_cluster_pct": 100},
        )
        snapshot = RiskSnapshot(profile_daily_loss_abs=Decimal("3500"))

        result = gate.check_intent(
            _intent(),
            profile,
            _sleeve(),
            _context(),
            snapshot=snapshot,
        )

        assert result.triggers_kill_switch is True

    def test_passes_with_position_sizing(self):
        gate = RiskGate()
        result = gate.check_intent(
            _intent(),
            _profile(),
            _sleeve(),
            _context(),
            atr=2.0,
            price=100.0,
        )

        assert result.allowed is True
        assert result.position_size is not None


class TestKillSwitchService:
    @pytest.mark.asyncio
    async def test_trigger_cancels_pending_intents(self):
        service = KillSwitchService()
        db = AsyncMock()

        pending = SimpleNamespace(
            id="intent-pending",
            status=DealIntentStatus.PENDING_APPROVAL.value,
            exit_logic={},
            updated_at=_NOW,
        )
        executing = SimpleNamespace(
            id="intent-exec",
            status=DealIntentStatus.EXECUTING.value,
            exit_logic={},
            updated_at=_NOW,
        )

        empty_ks = MagicMock()
        empty_ks.scalar_one_or_none.return_value = None

        intents_result = MagicMock()
        intents_result.scalars.return_value.all.return_value = [pending, executing]

        profile_row = SimpleNamespace(
            id="user-1",
            session_preferences={},
            updated_at=_NOW,
        )
        profiles_result = MagicMock()
        profiles_result.scalars.return_value.all.return_value = [profile_row]

        db.execute = AsyncMock(side_effect=[empty_ks, intents_result, profiles_result])

        row = await service.trigger(
            db,
            scope=KillSwitchScope.PROFILE,
            scope_id="user-1",
            reason="manual halt",
            trigger_type=KillSwitchTrigger.MANUAL,
        )

        assert row.active is True
        assert pending.status == DealIntentStatus.CANCELLED.value
        assert executing.status == DealIntentStatus.CANCELLED.value
        assert profile_row.session_preferences["strategies_stopped"] is True

    @pytest.mark.asyncio
    async def test_unlock_requires_comment(self):
        service = KillSwitchService()
        db = AsyncMock()
        with pytest.raises(ValueError, match="unlock comment is mandatory"):
            await service.unlock(
                db,
                scope=KillSwitchScope.PROFILE,
                scope_id="user-1",
                comment="   ",
            )


class TestAuditJournal:
    @pytest.mark.asyncio
    async def test_append_only_adds_record(self):
        journal = AuditJournal()
        db = AsyncMock()
        entry = await journal.append(
            db,
            action=ControlFabricAuditAction.RISK_GATE,
            resource_type="deal_intent",
            resource_id="intent-1",
            details={"outcome": "passed"},
        )
        db.add.assert_called_once()
        assert entry.action == ControlFabricAuditAction.RISK_GATE


class TestReplayEngine:
    def test_replay_reproduces_decisions(self):
        engine = ReplayEngine()
        profile = _profile()
        sleeve = _sleeve()
        intent = _intent()
        record = ReplayIntentRecord(
            intent_id="intent-1",
            instrument_id=101,
            sleeve_id="sleeve-1",
            profile_id="user-1",
            timestamp=_NOW.isoformat(),
            intent_snapshot=intent.model_dump(mode="json"),
            market_snapshot={
                "instrument_volatility": 0.2,
                "profile_drawdown_pct": 2.0,
                "profile_daily_loss_abs": "100",
                "max_correlation_with_portfolio": 0.3,
                "atr": 1.5,
                "price": 100.0,
            },
        )

        report = engine.replay(
            [record],
            profiles={"user-1": profile},
            sleeves={"sleeve-1": sleeve},
        )

        assert report.total == 1
        assert report.matched == 1
        assert report.decisions[0].risk_gate["allowed"] is True


def _trend_prices(start: float, step: float, count: int) -> list[float]:
    return [
        start + step * index + math.sin(index * 0.15) * 0.05
        for index in range(count)
    ]


class TestReplayEnginePredictionReplay:
    def test_trending_period_produces_regime_accuracy_report(self):
        engine = ReplayEngine()
        prices = _trend_prices(100.0, 2.0, 55)
        volumes = [1200.0 + index * 5 for index in range(len(prices))]

        report = engine.replay_predictions(
            instrument_id=101,
            prices=prices,
            volumes=volumes,
            spread_bps=6.0,
            forward_horizon=10,
            min_history=30,
        )

        assert report.instrument_id == 101
        assert report.total_points == 16
        assert report.regime_accuracy == pytest.approx(1.0)
        assert report.confusion_matrix.total == report.total_points
        assert report.confusion_matrix.accuracy == report.regime_accuracy
        assert report.confusion_matrix.matrix
        assert all(
            predicted_label in report.confusion_matrix.matrix
            for predicted_label in report.confusion_matrix.labels
        )
        assert report.forecast_calibration.bins
        assert len(report.points) == report.total_points
        assert all(point.predicted_regime for point in report.points)
        assert all(point.actual_regime for point in report.points)
        assert report.points[0].predicted_regime == MarketRegimeLabel.BULLISH_TREND.value
        assert report.points[0].regime_match is True
        assert 0.0 <= report.forecast_calibration.confidence_accuracy_correlation <= 1.0
        assert 0.0 <= report.risk_breach_rate <= 1.0

    def test_insufficient_history_raises(self):
        engine = ReplayEngine()
        with pytest.raises(ValueError, match="insufficient price history"):
            engine.replay_predictions(
                instrument_id=101,
                prices=_trend_prices(100.0, 1.0, 20),
            )


class TestControlFabricIntegration:
    @pytest.mark.asyncio
    async def test_breach_triggers_kill_switch_and_audit_trail(self):
        """Full scenario: breach → kill switch → cancel intents → audit trail."""
        fabric = ControlFabric()
        db = AsyncMock()

        pending_a = SimpleNamespace(
            id="intent-a",
            status=DealIntentStatus.PENDING_APPROVAL.value,
            exit_logic={},
            updated_at=_NOW,
        )
        pending_b = SimpleNamespace(
            id="intent-b",
            status=DealIntentStatus.APPROVED.value,
            exit_logic={},
            updated_at=_NOW,
        )

        audit_entries: list[SimpleNamespace] = []

        def capture_add(obj):
            audit_entries.append(obj)

        db.add = MagicMock(side_effect=capture_add)

        empty_ks = MagicMock()
        empty_ks.scalar_one_or_none.return_value = None

        intents_result = MagicMock()
        intents_result.scalars.return_value.all.return_value = [pending_a, pending_b]

        profile_row = SimpleNamespace(
            id="user-1",
            session_preferences={},
            updated_at=_NOW,
        )
        profiles_result = MagicMock()
        profiles_result.scalars.return_value.all.return_value = [profile_row]

        db.execute = AsyncMock(side_effect=[empty_ks, empty_ks, empty_ks, empty_ks, intents_result, profiles_result])

        profile = _profile(max_drawdown_pct=Decimal("5"))
        intent = _intent(id="intent-new")
        snapshot = RiskSnapshot(profile_drawdown_pct=8.0)

        result = await fabric.process_intent(
            db,
            intent=intent,
            profile=profile,
            sleeve=_sleeve(),
            context=_context(profile_drawdown_pct=8.0),
            snapshot=snapshot,
            actor="operator-1",
        )

        assert result.kill_switch_triggered is True
        assert result.risk_gate is not None
        assert result.risk_gate.triggers_kill_switch is True
        assert pending_a.status == DealIntentStatus.CANCELLED.value
        assert pending_b.status == DealIntentStatus.CANCELLED.value

        actions = [entry.action for entry in audit_entries if hasattr(entry, "action")]
        assert ControlFabricAuditAction.INTENT_CREATED in actions
        assert ControlFabricAuditAction.RISK_GATE in actions
        assert ControlFabricAuditAction.KILL_SWITCH_TRIGGERED in actions

    @pytest.mark.asyncio
    async def test_blocked_when_kill_switch_active(self):
        fabric = ControlFabric()
        db = AsyncMock()

        active_ks = SimpleNamespace(
            id="ks-1",
            scope=KillSwitchScope.PROFILE.value,
            scope_id="user-1",
            active=True,
            trigger_type=KillSwitchTrigger.MANUAL.value,
            reason="maintenance",
        )

        ks_result = MagicMock()
        ks_result.scalar_one_or_none.return_value = active_ks
        db.execute = AsyncMock(return_value=ks_result)
        db.add = MagicMock()

        result = await fabric.process_intent(
            db,
            intent=_intent(),
            profile=_profile(),
            sleeve=_sleeve(),
            context=_context(),
        )

        assert result.blocked_by_kill_switch is True
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_happy_path_runs_approval(self):
        fabric = ControlFabric()
        db = AsyncMock()

        empty_ks = MagicMock()
        empty_ks.scalar_one_or_none.return_value = None

        intent_row = SimpleNamespace(
            id="intent-1",
            status=DealIntentStatus.PENDING_APPROVAL.value,
            exit_logic={},
            updated_at=_NOW,
        )
        intent_result = MagicMock()
        intent_result.scalar_one_or_none.return_value = intent_row

        db.execute = AsyncMock(side_effect=[empty_ks, empty_ks, empty_ks, intent_result])
        db.add = MagicMock()

        result = await fabric.process_intent(
            db,
            intent=_intent(),
            profile=_profile(),
            sleeve=_sleeve(),
            context=_context(),
        )

        assert result.allowed is True
        assert result.approval_decision is not None
        assert result.approval_decision.state in {
            PolicyState.AUTO_APPROVE,
            PolicyState.CONDITIONAL_APPROVE,
        }
