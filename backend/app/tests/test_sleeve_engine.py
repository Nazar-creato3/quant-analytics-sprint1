"""Unit tests for SleeveEngine — budget, frozen gate, rebalance math."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.enums import AssetCategory, SleeveStatus
from app.domain.profile import ProfileBase, ProfileMode
from app.domain.compliance import AccountType, BrokerAgreementStatus, Jurisdiction
from app.domain.sleeve import SleeveRead
from app.services.sleeve import (
    IntentRiskRequest,
    RebalanceAction,
    SleeveEngine,
    SleevePositionSnapshot,
)


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


class TestRiskBudgetGate:
    def test_blocks_when_budget_exceeded(self):
        engine = SleeveEngine(total_capital_usd=100_000)
        sleeve = _sleeve(sleeve_id="s1", name="Core", allocation_pct="60", risk_budget="5000")
        positions = [
            SleevePositionSnapshot(sleeve_id="s1", market_value_usd=Decimal("4500")),
        ]
        intent = IntentRiskRequest(sleeve_id="s1", risk_amount_usd=Decimal("600"))

        result = engine.validate_new_intent(
            intent,
            sleeve,
            ProfileMode.PAPER,
            positions=positions,
        )

        assert result.allowed is False
        assert "risk budget exhausted" in result.reason

    def test_allows_when_within_budget(self):
        engine = SleeveEngine(total_capital_usd=100_000)
        sleeve = _sleeve(sleeve_id="s1", name="Core", allocation_pct="60", risk_budget="5000")
        positions = [
            SleevePositionSnapshot(sleeve_id="s1", market_value_usd=Decimal("3000")),
        ]
        intent = IntentRiskRequest(sleeve_id="s1", risk_amount_usd=Decimal("1500"))

        result = engine.validate_new_intent(
            intent,
            sleeve,
            ProfileMode.PAPER,
            positions=positions,
        )

        assert result.allowed is True

    def test_pending_intents_count_toward_budget(self):
        engine = SleeveEngine(total_capital_usd=100_000)
        sleeve = _sleeve(sleeve_id="s1", name="Core", allocation_pct="40", risk_budget="2000")
        pending = [IntentRiskRequest(sleeve_id="s1", risk_amount_usd=Decimal("1800"))]
        intent = IntentRiskRequest(sleeve_id="s1", risk_amount_usd=Decimal("300"))

        result = engine.validate_new_intent(
            intent,
            sleeve,
            ProfileMode.PAPER,
            pending_intents=pending,
        )

        assert result.allowed is False


class TestFrozenAndExperimentalGate:
    def test_blocks_frozen_sleeve(self):
        engine = SleeveEngine(total_capital_usd=50_000)
        sleeve = _sleeve(
            sleeve_id="s-frozen",
            name="Frozen",
            allocation_pct="20",
            risk_budget="10000",
            status=SleeveStatus.FROZEN,
        )
        intent = IntentRiskRequest(sleeve_id="s-frozen", risk_amount_usd=Decimal("100"))

        result = engine.validate_new_intent(intent, sleeve, ProfileMode.PAPER)

        assert result.allowed is False
        assert "frozen" in result.reason

    def test_blocks_experimental_in_live_mode(self):
        engine = SleeveEngine(total_capital_usd=50_000)
        sleeve = _sleeve(
            sleeve_id="s-exp",
            name="Lab",
            allocation_pct="5",
            risk_budget="1000",
            status=SleeveStatus.EXPERIMENTAL,
        )
        intent = IntentRiskRequest(sleeve_id="s-exp", risk_amount_usd=Decimal("50"))

        result = engine.validate_new_intent(intent, sleeve, ProfileMode.LIVE)

        assert result.allowed is False
        assert "experimental" in result.reason
        assert "paper mode" in result.reason

    def test_allows_experimental_in_paper_mode(self):
        engine = SleeveEngine(total_capital_usd=50_000)
        sleeve = _sleeve(
            sleeve_id="s-exp",
            name="Lab",
            allocation_pct="5",
            risk_budget="1000",
            status=SleeveStatus.EXPERIMENTAL,
        )
        intent = IntentRiskRequest(sleeve_id="s-exp", risk_amount_usd=Decimal("50"))

        result = engine.validate_new_intent(intent, sleeve, ProfileMode.PAPER)

        assert result.allowed is True


class TestCapitalAllocation:
    def test_allocation_targets_from_pct(self):
        engine = SleeveEngine(total_capital_usd=100_000)
        sleeves = [
            _sleeve(sleeve_id="a", name="A", allocation_pct="60", risk_budget="5000"),
            _sleeve(sleeve_id="b", name="B", allocation_pct="40", risk_budget="3000"),
        ]
        positions = [
            SleevePositionSnapshot(sleeve_id="a", market_value_usd=Decimal("2000")),
        ]

        targets = engine.allocation_targets(sleeves, positions=positions)

        assert len(targets) == 2
        by_id = {row.sleeve_id: row for row in targets}
        assert by_id["a"].target_capital_usd == Decimal("60000.00")
        assert by_id["b"].target_capital_usd == Decimal("40000.00")
        assert by_id["a"].risk_used_usd == Decimal("2000")
        assert by_id["a"].risk_remaining_usd == Decimal("3000")


class TestRebalance:
    def test_rebalance_math_two_sleeve_portfolio(self):
        engine = SleeveEngine(total_capital_usd=100_000)
        sleeves = [
            _sleeve(sleeve_id="eq", name="Equities", allocation_pct="60", risk_budget="10000"),
            _sleeve(sleeve_id="bond", name="Bonds", allocation_pct="40", risk_budget="5000"),
        ]
        positions = [
            SleevePositionSnapshot(sleeve_id="eq", market_value_usd=Decimal("50000")),
            SleevePositionSnapshot(sleeve_id="bond", market_value_usd=Decimal("30000")),
        ]

        plan = engine.rebalance("profile-1", sleeves, positions)

        assert plan.requires_deal_intent is True
        assert plan.total_deployed_usd == Decimal("80000")
        assert plan.total_capital_usd == Decimal("100000")

        by_id = {adj.sleeve_id: adj for adj in plan.adjustments}
        assert by_id["eq"].target_usd == Decimal("60000.00")
        assert by_id["eq"].current_usd == Decimal("50000")
        assert by_id["eq"].delta_usd == Decimal("10000.00")
        assert by_id["eq"].action == RebalanceAction.INCREASE
        assert by_id["eq"].current_pct == Decimal("50.00")
        assert by_id["eq"].target_pct == Decimal("60")

        assert by_id["bond"].target_usd == Decimal("40000.00")
        assert by_id["bond"].current_usd == Decimal("30000")
        assert by_id["bond"].delta_usd == Decimal("10000.00")
        assert by_id["bond"].action == RebalanceAction.INCREASE

    def test_rebalance_hold_when_on_target(self):
        engine = SleeveEngine(total_capital_usd=100_000)
        sleeves = [
            _sleeve(sleeve_id="only", name="Only", allocation_pct="100", risk_budget="5000"),
        ]
        positions = [
            SleevePositionSnapshot(sleeve_id="only", market_value_usd=Decimal("100000")),
        ]

        plan = engine.rebalance("profile-1", sleeves, positions)
        adj = plan.adjustments[0]

        assert adj.delta_usd == Decimal("0.00")
        assert adj.action == RebalanceAction.HOLD

    def test_rebalance_decrease_overweight_sleeve(self):
        engine = SleeveEngine(total_capital_usd=100_000)
        sleeves = [
            _sleeve(sleeve_id="heavy", name="Heavy", allocation_pct="50", risk_budget="8000"),
            _sleeve(sleeve_id="light", name="Light", allocation_pct="50", risk_budget="8000"),
        ]
        positions = [
            SleevePositionSnapshot(sleeve_id="heavy", market_value_usd=Decimal("70000")),
            SleevePositionSnapshot(sleeve_id="light", market_value_usd=Decimal("20000")),
        ]

        plan = engine.rebalance("profile-1", sleeves, positions)
        by_id = {adj.sleeve_id: adj for adj in plan.adjustments}

        assert by_id["heavy"].action == RebalanceAction.DECREASE
        assert by_id["heavy"].delta_usd == Decimal("-20000.00")
        assert by_id["light"].action == RebalanceAction.INCREASE
        assert by_id["light"].delta_usd == Decimal("30000.00")

    def test_rebalance_empty_portfolio_targets_full_allocation(self):
        engine = SleeveEngine(total_capital_usd=50_000)
        sleeves = [
            _sleeve(sleeve_id="a", name="A", allocation_pct="70", risk_budget="5000"),
            _sleeve(sleeve_id="b", name="B", allocation_pct="30", risk_budget="2000"),
        ]

        plan = engine.rebalance("profile-1", sleeves, positions=[])
        by_id = {adj.sleeve_id: adj for adj in plan.adjustments}

        assert plan.total_deployed_usd == Decimal("0")
        assert by_id["a"].current_usd == Decimal("0")
        assert by_id["a"].target_usd == Decimal("35000.00")
        assert by_id["a"].delta_usd == Decimal("35000.00")
        assert by_id["a"].action == RebalanceAction.INCREASE


def _compliance_profile(**overrides: object) -> ProfileBase:
    defaults = {
        "allowed_categories": [],
        "allowed_instrument_ids": [],
        "leverage_max": Decimal("1"),
        "mode": ProfileMode.LIVE,
        "jurisdiction": Jurisdiction.US,
        "account_type": AccountType.RETAIL,
        "broker_agreement_status": BrokerAgreementStatus.SIGNED,
    }
    defaults.update(overrides)
    return ProfileBase.model_validate(defaults)


class TestSleeveComplianceCombinedGate:
    def test_validate_new_intent_with_compliance_blocks_restricted_category(self):
        engine = SleeveEngine(total_capital_usd=50_000)
        sleeve = _sleeve(sleeve_id="s1", name="Core", allocation_pct="50", risk_budget="5000")
        profile = _compliance_profile()
        intent = IntentRiskRequest(
            sleeve_id="s1",
            risk_amount_usd=Decimal("100"),
            instrument_id=7,
            instrument_category=AssetCategory.CRYPTO,
        )

        result = engine.validate_new_intent_with_compliance(intent, sleeve, profile)

        assert result.allowed is False
        assert "blocked by compliance" in result.reason

    def test_validate_new_intent_with_compliance_passes_then_budget_check(self):
        engine = SleeveEngine(total_capital_usd=50_000)
        sleeve = _sleeve(sleeve_id="s1", name="Core", allocation_pct="50", risk_budget="5000")
        profile = _compliance_profile()
        intent = IntentRiskRequest(
            sleeve_id="s1",
            risk_amount_usd=Decimal("100"),
            instrument_id=7,
            instrument_category=AssetCategory.EQUITIES,
        )

        result = engine.validate_new_intent_with_compliance(intent, sleeve, profile)

        assert result.allowed is True


class TestCustomBasketSleeveContext:
    def test_basket_allocation_targets_within_sleeve_capital(self):
        from app.services.sleeve.types import CustomBasketItemSnapshot, CustomBasketSnapshot

        engine = SleeveEngine(total_capital_usd=Decimal("100000"))
        basket = CustomBasketSnapshot(
            basket_id="b1",
            name="Tech",
            sleeve_id="s1",
            items=(
                CustomBasketItemSnapshot(instrument_id=1, weight_pct=Decimal("60")),
                CustomBasketItemSnapshot(instrument_id=2, weight_pct=Decimal("40")),
            ),
        )
        targets = engine.basket_allocation_targets(
            basket,
            sleeve_target_capital_usd=Decimal("20000"),
        )
        assert len(targets) == 2
        assert targets[0].target_capital_usd == Decimal("12000.00")
        assert targets[1].target_capital_usd == Decimal("8000.00")

    def test_baskets_for_sleeve_filters_by_sleeve_id(self):
        from app.services.sleeve.types import CustomBasketItemSnapshot, CustomBasketSnapshot

        engine = SleeveEngine(total_capital_usd=Decimal("50000"))
        baskets = (
            CustomBasketSnapshot(
                basket_id="b1",
                name="Linked",
                sleeve_id="s1",
                items=(CustomBasketItemSnapshot(instrument_id=1, weight_pct=Decimal("100")),),
            ),
            CustomBasketSnapshot(
                basket_id="b2",
                name="Other",
                sleeve_id="s2",
                items=(CustomBasketItemSnapshot(instrument_id=2, weight_pct=Decimal("100")),),
            ),
        )
        linked = engine.baskets_for_sleeve("s1", baskets, sleeve_target_capital_usd=Decimal("10000"))
        assert len(linked) == 1
        assert linked[0].basket_id == "b1"
        assert linked[0].target_capital_usd == Decimal("10000.00")


class TestCustomBasketSleeveContext:
    def test_basket_allocation_targets_within_sleeve_capital(self):
        from app.services.sleeve.types import CustomBasketItemSnapshot, CustomBasketSnapshot

        engine = SleeveEngine(total_capital_usd=Decimal("100000"))
        basket = CustomBasketSnapshot(
            basket_id="b1",
            name="Tech",
            sleeve_id="s1",
            items=(
                CustomBasketItemSnapshot(instrument_id=1, weight_pct=Decimal("60")),
                CustomBasketItemSnapshot(instrument_id=2, weight_pct=Decimal("40")),
            ),
        )
        targets = engine.basket_allocation_targets(
            basket,
            sleeve_target_capital_usd=Decimal("20000"),
        )
        assert len(targets) == 2
        assert targets[0].target_capital_usd == Decimal("12000.00")
        assert targets[1].target_capital_usd == Decimal("8000.00")

    def test_baskets_for_sleeve_filters_by_sleeve_id(self):
        from app.services.sleeve.types import CustomBasketItemSnapshot, CustomBasketSnapshot

        engine = SleeveEngine(total_capital_usd=Decimal("50000"))
        baskets = (
            CustomBasketSnapshot(
                basket_id="b1",
                name="Linked",
                sleeve_id="s1",
                items=(CustomBasketItemSnapshot(instrument_id=1, weight_pct=Decimal("100")),),
            ),
            CustomBasketSnapshot(
                basket_id="b2",
                name="Other",
                sleeve_id="s2",
                items=(CustomBasketItemSnapshot(instrument_id=2, weight_pct=Decimal("100")),),
            ),
        )
        linked = engine.baskets_for_sleeve("s1", baskets, sleeve_target_capital_usd=Decimal("10000"))
        assert len(linked) == 1
        assert linked[0].basket_id == "b1"
        assert linked[0].target_capital_usd == Decimal("10000.00")
