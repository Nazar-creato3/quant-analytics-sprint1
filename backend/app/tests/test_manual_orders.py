"""Tests for manual order schemas and slippage helpers."""
from __future__ import annotations

import pytest

from app.schemas.orders import ManualOrderCreate


class TestManualOrderCreate:
    def test_market_order_valid(self):
        body = ManualOrderCreate(
            ticker="AAPL",
            side="buy",
            order_type="market",
            quantity=10,
        )
        assert body.order_type == "market"

    def test_limit_requires_price(self):
        with pytest.raises(ValueError, match="limit_price"):
            ManualOrderCreate(
                ticker="AAPL",
                side="buy",
                order_type="limit",
                quantity=10,
            )

    def test_oco_requires_sibling(self):
        with pytest.raises(ValueError, match="oco_sibling"):
            ManualOrderCreate(
                ticker="AAPL",
                side="buy",
                order_type="oco",
                quantity=10,
                stop_price=95,
            )

    def test_bracket_optional(self):
        from app.schemas.orders import BracketLeg

        body = ManualOrderCreate(
            ticker="AAPL",
            side="buy",
            order_type="limit",
            quantity=10,
            limit_price=150,
            bracket=BracketLeg(stop_loss=140, take_profit=165),
        )
        assert body.bracket.take_profit == 165


class TestManualOrderModify:
    def test_requires_at_least_one_field(self):
        from app.schemas.orders import ManualOrderModify

        with pytest.raises(ValueError, match="limit_price or quantity"):
            ManualOrderModify()

    def test_accepts_limit_and_qty(self):
        from app.schemas.orders import ManualOrderModify

        body = ManualOrderModify(limit_price=150.5, quantity=12)
        assert body.limit_price == 150.5
        assert body.quantity == 12


class TestSlippageEstimate:
    def test_warning_when_large_participation(self):
        from app.services.orders.slippage import SlippageEstimate

        est = SlippageEstimate(
            estimated_slippage_bps=30,
            estimated_avg_fill=100,
            warning="large order",
            visible_liquidity_usd=1000,
        )
        assert est.warning is not None
