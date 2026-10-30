"""Tests for Prompt 26 Risk Budget Allocator in SleeveEngine."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.domain.enums import AssetCategory, SleeveStatus, Strategy
from app.domain.sleeve import SleeveRead
from app.services.control_fabric.types import ReplayIntentRecord
from app.services.regime.types import MarketRegimeLabel
from app.services.sleeve import SleeveEngine


def _sleeve(
    *,
    sleeve_id: str,
    name: str,
    allocation_pct: str,
    risk_budget: str,
    status: SleeveStatus = SleeveStatus.ACTIVE,
    category: AssetCategory = AssetCategory.EQUITIES,
) -> SleeveRead:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return SleeveRead(
        id=sleeve_id,
        profile_id="profile-1",
        name=name,
        category=category,
        capital_allocation_pct=Decimal(allocation_pct),
        risk_budget=Decimal(risk_budget),
        status=status,
        created_at=now,
        updated_at=now,
    )


def _portfolio() -> list[SleeveRead]:
    return [
        _sleeve(
            sleeve_id="defensive",
            name="Defensive",
            allocation_pct="30",
            risk_budget="3000",
            category=AssetCategory.DEFENSIVE_SLEEVE,
        ),
        _sleeve(
            sleeve_id="core",
            name="Core Equities",
            allocation_pct="50",
            risk_budget="5000",
            category=AssetCategory.EQUITIES,
        ),
        _sleeve(
            sleeve_id="speculative",
            name="Speculative",
            allocation_pct="15",
            risk_budget="1500",
            category=AssetCategory.SPECULATIVE_SLEEVE,
        ),
        _sleeve(
            sleeve_id="lab",
            name="Experimental Lab",
            allocation_pct="5",
            risk_budget="500",
            status=SleeveStatus.EXPERIMENTAL,
            category=AssetCategory.CRYPTO,
        ),
    ]


class TestRiskBudgetAllocator:
    def test_bullish_trend_boosts_trend_strategies(self):
        engine = SleeveEngine(total_capital_usd=100_000)
        sleeves = _portfolio()
        strategies = {
            "core": (Strategy.TREND, Strategy.MEAN_REVERSION),
        }

        allocation = engine.risk_budget_allocation(
            sleeves,
            total_var_budget_usd=Decimal("10000"),
            strategies_by_sleeve=strategies,
            regime=MarketRegimeLabel.BULLISH_TREND.value,
            regime_confidence=0.80,
        )

        assert allocation.total_var_budget_usd == Decimal("10000")
        assert sum(allocation.sleeve_var_budget_usd.values()) == Decimal("10000.00")

        by_strategy = {
            (target.sleeve_id, target.strategy): target for target in allocation.strategy_targets
        }
        trend = by_strategy[("core", Strategy.TREND)].target_var_budget_usd
        mean_rev = by_strategy[("core", Strategy.MEAN_REVERSION)].target_var_budget_usd
        assert trend > mean_rev

    def test_high_volatility_shock_cuts_speculative_and_experimental(self):
        engine = SleeveEngine(total_capital_usd=100_000)
        sleeves = _portfolio()

        bullish = engine.risk_budget_allocation(
            sleeves,
            total_var_budget_usd=Decimal("10000"),
            regime=MarketRegimeLabel.BULLISH_TREND.value,
            regime_confidence=0.75,
        )
        shock = engine.risk_budget_allocation(
            sleeves,
            total_var_budget_usd=Decimal("10000"),
            regime=MarketRegimeLabel.HIGH_VOLATILITY_SHOCK.value,
            regime_confidence=0.90,
        )

        assert shock.sleeve_var_budget_usd["speculative"] < bullish.sleeve_var_budget_usd["speculative"]
        assert shock.sleeve_var_budget_usd["lab"] < bullish.sleeve_var_budget_usd["lab"]
        assert shock.sleeve_var_budget_usd["defensive"] >= bullish.sleeve_var_budget_usd["defensive"] * Decimal(
            "0.95"
        )
        assert shock.sleeve_var_budget_usd["speculative"] <= bullish.sleeve_var_budget_usd["speculative"] * Decimal(
            "0.25"
        )
        assert shock.sleeve_var_budget_usd["lab"] <= bullish.sleeve_var_budget_usd["lab"] * Decimal("0.20")

    def test_rebalance_risk_budget_returns_plan_not_execution(self):
        engine = SleeveEngine(total_capital_usd=100_000)
        sleeves = _portfolio()

        plan = engine.rebalance_risk_budget(
            "profile-1",
            sleeves,
            total_var_budget_usd=Decimal("10000"),
            regime=MarketRegimeLabel.HIGH_VOLATILITY_SHOCK.value,
            regime_confidence=0.85,
        )

        assert plan.requires_deal_intent is True
        assert plan.profile_id == "profile-1"
        assert len(plan.adjustments) == 4
        by_id = {adj.sleeve_id: adj for adj in plan.adjustments}
        assert by_id["speculative"].delta_var_budget_usd < 0
        assert by_id["lab"].delta_var_budget_usd < 0

    def test_replay_history_weights_effective_strategies(self):
        engine = SleeveEngine(total_capital_usd=100_000)
        sleeves = [
            _sleeve(
                sleeve_id="core",
                name="Core",
                allocation_pct="100",
                risk_budget="10000",
            )
        ]
        records = [
            ReplayIntentRecord(
                intent_id="i1",
                instrument_id=1,
                sleeve_id="core",
                profile_id="profile-1",
                timestamp="2026-01-01T00:00:00Z",
                intent_snapshot={"strategy": Strategy.TREND.value},
                market_snapshot={
                    "market_regime": MarketRegimeLabel.BULLISH_TREND.value,
                    "replay_risk_allowed": True,
                    "replay_approval_allowed": True,
                },
            ),
            ReplayIntentRecord(
                intent_id="i2",
                instrument_id=2,
                sleeve_id="core",
                profile_id="profile-1",
                timestamp="2026-01-02T00:00:00Z",
                intent_snapshot={"strategy": Strategy.TREND.value},
                market_snapshot={
                    "market_regime": MarketRegimeLabel.BULLISH_TREND.value,
                    "replay_risk_allowed": True,
                    "replay_approval_allowed": True,
                },
            ),
            ReplayIntentRecord(
                intent_id="i3",
                instrument_id=3,
                sleeve_id="core",
                profile_id="profile-1",
                timestamp="2026-01-03T00:00:00Z",
                intent_snapshot={"strategy": Strategy.MEAN_REVERSION.value},
                market_snapshot={
                    "market_regime": MarketRegimeLabel.BULLISH_TREND.value,
                    "replay_risk_allowed": True,
                    "replay_approval_allowed": False,
                },
            ),
        ]

        allocation = engine.risk_budget_allocation(
            sleeves,
            total_var_budget_usd=Decimal("10000"),
            strategies_by_sleeve={"core": (Strategy.TREND, Strategy.MEAN_REVERSION)},
            regime=MarketRegimeLabel.BULLISH_TREND.value,
            regime_confidence=0.70,
            replay_records=records,
        )

        by_strategy = {
            target.strategy: target for target in allocation.strategy_targets
        }
        assert by_strategy[Strategy.TREND].replay_effectiveness > by_strategy[
            Strategy.MEAN_REVERSION
        ].replay_effectiveness
        assert (
            by_strategy[Strategy.TREND].target_var_budget_usd
            > by_strategy[Strategy.MEAN_REVERSION].target_var_budget_usd
        )
