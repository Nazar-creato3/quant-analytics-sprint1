from __future__ import annotations

import pytest

from app.services.trading_engines.runtime.prices import resolve_close_prices


def test_missing_prices_are_not_invented():
    with pytest.raises(ValueError, match="нет данных"):
        resolve_close_prices({})
    with pytest.raises(ValueError, match="нет данных"):
        resolve_close_prices({"prices": [1, 2, 3]})


def test_supplied_prices_are_used():
    row = [float(i) for i in range(10, 20)]
    assert resolve_close_prices({"prices": row}) == row
