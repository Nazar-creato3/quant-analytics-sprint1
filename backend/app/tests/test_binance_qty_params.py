from __future__ import annotations

import pytest

from app.services.trading_keys.binance_qty import binance_order_qty_params


def test_binance_fractional_without_price_is_refused():
    with pytest.raises(ValueError, match="нет данных"):
        binance_order_qty_params(0.01, None)


def test_binance_fractional_below_min_notional_is_refused():
    with pytest.raises(ValueError, match="нет данных"):
        binance_order_qty_params(0.001, 100)


def test_binance_whole_qty_uses_quantity_not_inflated_quote():
    assert binance_order_qty_params(2, None) == {"quantity": "2"}
    params = binance_order_qty_params(0.1, 150)
    assert params == {"quoteOrderQty": "15.0"}
    assert "15.0" in params["quoteOrderQty"]
