"""Unit tests for CustomBasket domain entity."""
from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain.custom_basket import (
    CustomBasketCreate,
    CustomBasketItemCreate,
    CustomBasketORM,
    validate_basket_composition,
)


def _items(*pairs: tuple[int, str]) -> list[CustomBasketItemCreate]:
    return [
        CustomBasketItemCreate(instrument_id=instrument_id, weight_pct=Decimal(weight))
        for instrument_id, weight in pairs
    ]


class TestValidateBasketComposition:
    def test_valid_two_instrument_basket(self):
        items = _items((1, "60"), (2, "40"))
        validate_basket_composition(items)

    def test_rejects_empty_basket(self):
        with pytest.raises(ValueError, match="at least one instrument"):
            validate_basket_composition([])

    def test_rejects_duplicate_instruments(self):
        items = _items((1, "50"), (1, "50"))
        with pytest.raises(ValueError, match="duplicate instrument_id"):
            validate_basket_composition(items)

    def test_rejects_weights_not_summing_to_100(self):
        items = _items((1, "60"), (2, "30"))
        with pytest.raises(ValueError, match="must sum to 100"):
            validate_basket_composition(items)


class TestCustomBasketCreate:
    def test_create_with_sleeve_context(self):
        basket = CustomBasketCreate(
            name="Tech Core",
            description="User tech basket",
            sleeve_id="sleeve-1",
            items=_items((10, "70"), (11, "30")),
        )
        assert basket.name == "Tech Core"
        assert basket.sleeve_id == "sleeve-1"
        assert len(basket.items) == 2

    def test_rejects_blank_name(self):
        with pytest.raises(ValidationError):
            CustomBasketCreate(
                name="   ",
                items=_items((1, "100")),
            )

    def test_rejects_invalid_composition(self):
        with pytest.raises(ValidationError):
            CustomBasketCreate(
                name="Bad Weights",
                items=_items((1, "55"), (2, "55")),
            )


class TestCustomBasketORM:
    def test_orm_tablename(self):
        assert CustomBasketORM.__tablename__ == "custom_baskets"
