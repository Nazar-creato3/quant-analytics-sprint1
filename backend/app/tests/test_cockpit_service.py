"""Unit tests for Asset Cockpit read model helpers."""
from __future__ import annotations

from app.domain.enums import AssetCategory
from app.services.cockpit.service import (
    _bot_suitability,
    _liquidity_state,
    _spread_state,
    _volatility_bands,
)


class TestCockpitHelpers:
    def test_liquidity_state_deep(self):
        assert _liquidity_state(10_000_000, AssetCategory.EQUITIES) == "deep"

    def test_spread_state_tight(self):
        assert _spread_state(3.5) == "tight"

    def test_volatility_bands(self):
        bands = _volatility_bands([100.0, 101.0, 99.5, 102.0, 100.5])
        assert bands.mid > 0
        assert bands.upper >= bands.mid >= bands.lower

    def test_bot_suitability_bounded(self):
        score = _bot_suitability(
            category=AssetCategory.CRYPTO,
            regime="sideways",
            liquidity="deep",
            spread="tight",
            volatility=0.15,
        )
        assert 0 <= score <= 100
