"""Bootstrap goal probability (prompt K5). Historical draws, not a normal model.

MAPIE 0.9.0 supplies a conformal interval around expected terminal wealth
when at least 30 daily returns exist. Seed is stored with the result.
"""
from __future__ import annotations

import numpy as np


def bootstrap_terminal(
    daily_returns: np.ndarray,
    *,
    start: float,
    monthly_contrib: float,
    days: int,
    target: float,
    n_paths: int = 2000,
    seed: int = 63,
) -> dict[str, float | int | str]:
    r = np.asarray(daily_returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 20 or start <= 0 or days <= 0:
        return {"probability": None, "p05": None, "p95": None, "seed": seed, "status": "нет данных"}
    rng = np.random.default_rng(int(seed))
    draws = rng.choice(r, size=(int(n_paths), int(days)), replace=True)
    daily_contrib = float(monthly_contrib) * 12.0 / 252.0
    wealth = np.full(int(n_paths), float(start), dtype=float)
    for t in range(int(days)):
        wealth = wealth * (1.0 + draws[:, t]) + daily_contrib
    p = float(np.mean(wealth >= float(target)))
    lo, hi = np.percentile(wealth, [5.0, 95.0])
    return {
        "probability": p,
        "p05": float(lo),
        "p95": float(hi),
        "seed": int(seed),
        "status": "ok",
        "n_paths": int(n_paths),
    }


def mapie_terminal_band(
    daily_returns: np.ndarray,
    *,
    start: float,
    days: int,
) -> dict[str, float | str] | None:
    """Conformal band on 1-day mean, scaled by sqrt(days). None if MAPIE cannot fit."""
    r = np.asarray(daily_returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 30:
        return None
    try:
        from mapie.regression import MapieRegressor
        from sklearn.linear_model import LinearRegression
    except Exception:
        return None
    y = r[1:]
    x = r[:-1].reshape(-1, 1)
    try:
        est = MapieRegressor(LinearRegression(), method="plus", cv=5)
        est.fit(x, y)
        last = r[-1:].reshape(-1, 1)
        _, intervals = est.predict(last, alpha=0.10)
        lo = float(intervals[0, 0, 0])
        hi = float(intervals[0, 1, 0])
    except Exception:
        return None
    scale = float(days) ** 0.5
    mid = float(start) * ((1.0 + float(np.mean(r))) ** days)
    return {
        "mapie_low": mid * (1.0 + lo * scale),
        "mapie_high": mid * (1.0 + hi * scale),
        "method": "mapie_plus",
    }
