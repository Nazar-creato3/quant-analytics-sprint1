"""Unit tests for Strategy enum validation usage."""
from __future__ import annotations

import pytest

from app.domain.enums import Strategy


class TestStrategyEnum:
    @pytest.mark.parametrize(
        "value",
        [
            "grid",
            "trend",
            "mean_reversion",
            "breakout",
            "hedge",
            "income",
            "rotation",
            "volatility_harvesting",
        ],
    )
    def test_valid_strategy_values(self, value: str):
        assert Strategy(value).value == value

    def test_invalid_strategy_rejected(self):
        with pytest.raises(ValueError):
            Strategy("momentum")

    def test_strategy_count(self):
        assert len(Strategy) == 8
