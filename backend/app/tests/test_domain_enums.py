"""Unit tests for domain enums and taxonomy."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.enums import (
    AssetCategory,
    CATEGORY_PARENTS,
    InstrumentSource,
    SleeveStatus,
    Strategy,
    TradableUnit,
)
from app.domain.instrument import InstrumentCreate
from app.domain.sleeve import SleeveCreate
from app.domain.taxonomy import ancestors_of, children_of, is_descendant_of, is_root, parent_of


class TestAssetCategory:
    def test_all_categories_have_parent_mapping(self):
        for category in AssetCategory:
            assert category in CATEGORY_PARENTS

    def test_hierarchy_roots(self):
        assert is_root(AssetCategory.EQUITIES)
        assert is_root(AssetCategory.CRYPTO)
        assert not is_root(AssetCategory.THEMATIC_BASKET)

    def test_hierarchy_descendants(self):
        assert parent_of(AssetCategory.THEMATIC_BASKET) == AssetCategory.EQUITIES
        assert is_descendant_of(AssetCategory.SECTOR_BASKET, AssetCategory.EQUITIES)
        assert not is_descendant_of(AssetCategory.CRYPTO, AssetCategory.EQUITIES)

    def test_ancestors_and_children(self):
        assert ancestors_of(AssetCategory.THEMATIC_BASKET) == (AssetCategory.EQUITIES,)
        assert AssetCategory.THEMATIC_BASKET in children_of(AssetCategory.EQUITIES)


class TestInstrumentSource:
    def test_valid_sources(self):
        assert InstrumentSource("binance") == InstrumentSource.BINANCE
        assert InstrumentSource("finam") == InstrumentSource.FINAM

    def test_invalid_source_rejected(self):
        with pytest.raises(ValueError):
            InstrumentSource("alpaca")


class TestStrategy:
    def test_all_strategies(self):
        values = {item.value for item in Strategy}
        assert values == {
            "grid",
            "trend",
            "mean_reversion",
            "breakout",
            "hedge",
            "income",
            "rotation",
            "volatility_harvesting",
        }


class TestTradableUnit:
    def test_per_share_default_on_instrument(self):
        inst = InstrumentCreate(
            symbol="SBER",
            category=AssetCategory.EQUITIES,
            source=InstrumentSource.MOEX,
        )
        assert inst.tradable_unit == TradableUnit.PER_SHARE


class TestSleeveStatus:
    def test_valid_status_values(self):
        assert SleeveStatus.ACTIVE.value == "active"
        assert SleeveStatus.FROZEN.value == "frozen"
        assert SleeveStatus.EXPERIMENTAL.value == "experimental"


class TestCrossEntityValidation:
    def test_instrument_rejects_blank_symbol(self):
        with pytest.raises(ValidationError):
            InstrumentCreate(
                symbol="   ",
                category=AssetCategory.ETF,
                source=InstrumentSource.TINKOFF,
            )

    def test_sleeve_rejects_allocation_over_100(self):
        from decimal import Decimal

        with pytest.raises(ValidationError):
            SleeveCreate(
                profile_id="user-1",
                name="Core",
                category=AssetCategory.INCOME_SLEEVE,
                capital_allocation_pct=Decimal("100.01"),
                risk_budget=Decimal("5000"),
            )
