"""Integration tests for maneuver generation tradeable count."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timezone

from app.core.config import settings
from app.services.risk.maneuver_generator import ManeuverGenerator


def _make_df(seed: int, trend: float = 0.001) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = 300
    dates = pd.date_range(end=datetime.now(timezone.utc), periods=n, freq="D")
    close = 100 * np.cumprod(1 + rng.normal(0, 0.02, n) + trend)
    return pd.DataFrame(
        {
            "open": close * 0.99,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": rng.integers(1_000_000, 5_000_000, n),
        },
        index=dates,
    )


def _default_watchlist_data() -> dict[str, pd.DataFrame]:
    tickers = settings.default_watchlist_list
    return {t: _make_df(i, trend=(i - 5) * 0.0005) for i, t in enumerate(tickers)}


class TestManeuverGeneration:
    def test_default_watchlist_produces_reasonable_tradeable_count(self):
        gen = ManeuverGenerator()
        outs = gen.generate(market_data=_default_watchlist_data())
        tradeable = [m for m in outs if not m.is_no_trade]

        assert len(outs) == settings.MANEUVER_COUNT
        # With 10 tickers we expect most slots to be tradeable, not just 1-2.
        assert len(tradeable) >= min(6, len(settings.default_watchlist_list))

    def test_confidence_adjustment_does_not_over_penalize(self, monkeypatch):
        monkeypatch.setattr(settings, "NO_TRADE_CONFIDENCE_THRESHOLD", 0.45)
        gen = ManeuverGenerator()
        outs = gen.generate(market_data=_default_watchlist_data())
        tradeable = [m for m in outs if not m.is_no_trade]
        assert len(tradeable) >= 5

    def test_high_live_exposure_does_not_cap_tradeable_slots(self):
        """Analysis fills slots from watchlist; live exposure limits execution only."""
        from app.services.risk.engine import PortfolioState

        gen = ManeuverGenerator()
        data = _default_watchlist_data()
        saturated = PortfolioState(total_exposure_usd=75_000, open_positions=8)
        outs = gen.generate(market_data=data, portfolio_state=saturated)
        tradeable = [m for m in outs if not m.is_no_trade]
        assert len(tradeable) >= min(6, len(settings.default_watchlist_list))
