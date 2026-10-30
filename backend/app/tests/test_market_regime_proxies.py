"""ETN/ETF prices must not be read as VIX level or credit spread (blocked all trades)."""
import numpy as np
import pandas as pd

from app.services.pipeline.market_regime import compute_market_regime


def _frame(start: float, drift: float, n: int = 80, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = start * np.exp(np.cumsum(drift + 0.004 * rng.standard_normal(n)))
    return pd.DataFrame({"close": closes})


def test_hyg_and_vxx_prices_do_not_force_shock():
    data = {
        "SPY": _frame(500, 0.002, seed=1),
        "QQQ": _frame(450, 0.002, seed=2),
        "IWM": _frame(200, 0.001, seed=3),
        "EEM": _frame(45, 0.001, seed=4),
        "TLT": _frame(90, 0.0, seed=5),
        "VXX": _frame(48, 0.0, seed=6),  # ETN price, far above VIX 32 threshold
        "HYG": _frame(80, 0.0, seed=7),  # fund price, far above 1.5 spread threshold
    }
    out = compute_market_regime(data)
    assert out["credit"] is None
    assert out["vix"] is None
    assert out["macro_veto"] is False
    assert out["regime_gate"] != "shock"


def test_real_spread_still_counts():
    data = {"SPY": _frame(500, 0.002, seed=1), "BAMLH0A0HYM2": _frame(4.0, 0.0, seed=8)}
    out = compute_market_regime(data)
    assert out["credit"] is not None and out["credit"] > 1.5
