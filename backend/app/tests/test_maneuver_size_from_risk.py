"""Fresh generate: risk% must convert to a positive USD size for real names."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app.services.risk.maneuver_generator import ManeuverGenerator


def _ohlcv(seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = 120
    close = 180 * np.cumprod(1 + rng.normal(0.0004, 0.012, n))
    return pd.DataFrame(
        {
            "open": close * 0.998,
            "high": close * 1.008,
            "low": close * 0.992,
            "close": close,
            "volume": rng.integers(2_000_000, 8_000_000, n),
        },
        index=pd.date_range(end=datetime.now(timezone.utc), periods=n, freq="D"),
    )


def test_generate_msft_aapl_amzn_nonzero_size_when_portfolio_unset():
    """Paper path: DEFAULT cap 0 must still resolve a fallback and write USD."""
    gen = ManeuverGenerator(portfolio_size=0.0, confidence_threshold=0.40)
    assert gen.portfolio_size > 0
    outs = gen.generate(
        market_data={"MSFT": _ohlcv(1), "AAPL": _ohlcv(2), "AMZN": _ohlcv(3)},
        user_id="paper",
    )
    live = [m for m in outs if not m.is_no_trade and m.ticker in {"MSFT", "AAPL", "AMZN"}]
    assert live, "expected at least one real-name slot"
    broken = [
        m
        for m in live
        if (m.risk_percent or 0) > 0 and float(m.position_size_usd or 0) <= 0
    ]
    assert not broken, [
        (m.ticker, m.strategy_type, m.risk_percent, m.position_size_usd)
        for m in broken
    ]
    sized = [m for m in live if float(m.position_size_usd or 0) > 0]
    assert sized, "conversion risk% → $ did not produce a ticket"
    for m in sized:
        assert m.strategy_type != "no_trade"
        assert m.position_size_usd > 0
        assert m.risk_percent > 0
