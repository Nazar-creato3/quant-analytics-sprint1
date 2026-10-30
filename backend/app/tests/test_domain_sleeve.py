"""Unit tests for Sleeve domain entity."""
from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain.enums import AssetCategory, SleeveStatus
from app.domain.sleeve import SleeveCreate, SleeveORM


class TestSleeveCreate:
    def test_create_active_sleeve(self):
        sleeve = SleeveCreate(
            profile_id="550e8400-e29b-41d4-a716-446655440000",
            name="Income Core",
            category=AssetCategory.INCOME_SLEEVE,
            capital_allocation_pct=Decimal("25.00"),
            risk_budget=Decimal("10000"),
        )
        assert sleeve.status == SleeveStatus.ACTIVE
        assert sleeve.name == "Income Core"

    def test_create_frozen_sleeve(self):
        sleeve = SleeveCreate(
            profile_id="550e8400-e29b-41d4-a716-446655440000",
            name="Speculative",
            category=AssetCategory.SPECULATIVE_SLEEVE,
            capital_allocation_pct=Decimal("10"),
            risk_budget=Decimal("2500"),
            status=SleeveStatus.FROZEN,
        )
        assert sleeve.status == SleeveStatus.FROZEN

    def test_rejects_negative_risk_budget(self):
        with pytest.raises(ValidationError):
            SleeveCreate(
                profile_id="user-1",
                name="Bad",
                category=AssetCategory.DEFENSIVE_SLEEVE,
                capital_allocation_pct=Decimal("5"),
                risk_budget=Decimal("-1"),
            )

    def test_rejects_negative_allocation(self):
        with pytest.raises(ValidationError):
            SleeveCreate(
                profile_id="user-1",
                name="Bad",
                category=AssetCategory.DEFENSIVE_SLEEVE,
                capital_allocation_pct=Decimal("-0.01"),
                risk_budget=Decimal("100"),
            )

    def test_rejects_blank_name(self):
        with pytest.raises(ValidationError):
            SleeveCreate(
                profile_id="user-1",
                name="   ",
                category=AssetCategory.CUSTOM_USER_BASKET,
                capital_allocation_pct=Decimal("15"),
                risk_budget=Decimal("500"),
            )

    def test_boundary_allocation_100(self):
        sleeve = SleeveCreate(
            profile_id="user-1",
            name="Full",
            category=AssetCategory.EQUITIES,
            capital_allocation_pct=Decimal("100"),
            risk_budget=Decimal("0"),
        )
        assert sleeve.capital_allocation_pct == Decimal("100")


class TestSleeveORM:
    def test_orm_tablename_and_fields(self):
        assert SleeveORM.__tablename__ == "sleeves"
        orm = SleeveORM(
            profile_id="user-1",
            name="Test Sleeve",
            category=AssetCategory.MACRO_HEDGE.value,
            capital_allocation_pct=Decimal("20"),
            risk_budget=Decimal("5000"),
            status=SleeveStatus.EXPERIMENTAL.value,
        )
        assert orm.name == "Test Sleeve"
        assert orm.category == AssetCategory.MACRO_HEDGE.value
