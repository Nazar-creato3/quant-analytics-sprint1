"""Tests for symbol trading rules and order validation."""
from __future__ import annotations

import pytest

from app.services.orders.symbol_rules import (
    SymbolTradingRules,
    round_price,
    round_qty,
    validate_order_qty_price,
)


def test_validate_crypto_qty_step():
    rules = SymbolTradingRules(
        ticker="BTCUSDT",
        venue="binance",
        tick_size=0.01,
        lot_size=0.0001,
        min_qty=0.0001,
        min_notional_usd=5.0,
        price_decimals=2,
        qty_decimals=4,
    )
    errors = validate_order_qty_price(qty=0.00015, price=65000.0, rules=rules)
    assert any("multiple" in e for e in errors)


def test_round_price_and_qty():
    rules = SymbolTradingRules(
        ticker="TSLA",
        venue="us",
        tick_size=0.01,
        lot_size=1.0,
        min_qty=1.0,
        price_decimals=2,
        qty_decimals=0,
    )
    assert round_price(123.456, rules) == 123.46
    assert round_qty(10.7, rules) == 10.0


def test_us_min_qty():
    rules = SymbolTradingRules(
        ticker="MSFT",
        venue="us",
        tick_size=0.01,
        lot_size=1.0,
        min_qty=1.0,
        min_notional_usd=0.0,
    )
    errors = validate_order_qty_price(qty=0.5, price=400.0, rules=rules)
    assert any("Minimum quantity" in e for e in errors)


@pytest.mark.asyncio
async def test_get_symbol_trading_rules_us_defaults():
    from app.services.orders.symbol_rules import get_symbol_trading_rules

    rules = await get_symbol_trading_rules("TSLA")
    assert rules.venue == "us"
    assert rules.tick_size > 0
    assert rules.lot_size >= 1.0
