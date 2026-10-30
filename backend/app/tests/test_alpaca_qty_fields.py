from __future__ import annotations

import pytest

from app.services.execution.alpaca_qty import alpaca_order_qty_fields


def test_fractional_without_price_is_refused():
    with pytest.raises(ValueError, match="нет данных"):
        alpaca_order_qty_fields(0.5, None)


def test_fractional_uses_price_not_one_thousand():
    assert alpaca_order_qty_fields(0.5, 80) == {"notional": 40.0}


def test_whole_qty_is_not_truncated_to_int():
    assert alpaca_order_qty_fields(1.9, None) == {"qty": "1.9"}
