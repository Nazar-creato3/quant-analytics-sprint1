"""Kakushadze / Hasbrouck features on the existing OHLCV → book_gate path.

Not a parallel store. Kyle and Alpha#3 stay blocked until their data/infra exist.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

# Snapshot NBBO from Phase 1 is not a trade-signed tape (Hasbrouck / Kyle).
KYLE_STATUS = {
    "status": "blocked",
    "reason": (
        "book_gate after Phase 1 gets a prefetch snapshot (top_of_book), "
        "not bid/ask at each trade. Recipe forbids daily-bar or snapshot "
        "approximation of signed order flow."
    ),
}

ALPHA003_STATUS = {
    "status": "skipped",
    "reason": (
        "Alpha#3 is cross-sectional rank(open)/rank(volume) over the full "
        "universe. generate() is per-symbol; no PIT cross-section ranker."
    ),
}


def _col(df: pd.DataFrame, *names: str) -> str | None:
    lower = {str(c).lower(): c for c in df.columns}
    for n in names:
        if n in df.columns:
            return n
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def session_vwap_approx(*, open_: float, high: float, low: float, close: float) -> float:
    """Kakushadze 2016 default VWAP when tick VWAP is unavailable.

    (close + (open + high + low) / 3) / 2  — not interchangeable with true VWAP.
    """
    typical = (open_ + high + low) / 3.0
    return (close + typical) / 2.0


def alpha041_vwap_deviation(row: Mapping[str, Any]) -> dict[str, Any]:
    """Alpha#41: sqrt(high * low) - vwap. Last completed session only."""
    try:
        high = float(row["high"])
        low = float(row["low"])
        open_ = float(row["open"])
        close = float(row["close"])
    except (KeyError, TypeError, ValueError):
        return {
            "vwap_deviation": None,
            "vwap_deviation_rel": None,
            "vwap_source": "unavailable",
        }
    if min(high, low, open_, close) <= 0 or not all(
        math.isfinite(x) for x in (high, low, open_, close)
    ):
        return {
            "vwap_deviation": None,
            "vwap_deviation_rel": None,
            "vwap_source": "unavailable",
        }
    vwap = session_vwap_approx(open_=open_, high=high, low=low, close=close)
    geom = math.sqrt(high * low)
    dev = geom - vwap
    return {
        "vwap_deviation": dev,
        "vwap_deviation_rel": dev / close,
        "vwap": vwap,
        "geom_price": geom,
        "vwap_source": "kakushadze_ohlc_approx",
    }


def _autocovariance(dp: np.ndarray) -> float | None:
    if dp.size < 3:
        return None
    x = dp[:-1]
    y = dp[1:]
    if x.size < 2:
        return None
    x = x.astype(float)
    y = y.astype(float)
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        return None
    return float(np.cov(x, y, ddof=1)[0, 1])


def roll_effective_spread(prices: Sequence[float], *, window: int = 20) -> float | None:
    """Hasbrouck / Roll: 2 * sqrt(-γ1). γ1 ≥ 0 → None, never clamped to 0."""
    arr = np.asarray([float(p) for p in prices if p is not None], dtype=float)
    arr = arr[np.isfinite(arr) & (arr > 0)]
    if arr.size < window + 1:
        return None
    dp = np.diff(arr[-(window + 1) :])
    gamma1 = _autocovariance(dp)
    if gamma1 is None or gamma1 >= 0:
        return None
    return 2.0 * math.sqrt(-gamma1)


def roll_spread_zscore(
    prices: Sequence[float],
    *,
    window: int = 20,
    median_lookback: int = 30,
) -> dict[str, Any]:
    """spread / trailing median → z-score. Daily closes if no 1-min tape."""
    arr = [float(p) for p in prices if p is not None]
    arr = [p for p in arr if math.isfinite(p) and p > 0]
    need = window + median_lookback
    if len(arr) < need:
        return {
            "spread": None,
            "spread_zscore": None,
            "gamma1_ok": False,
            "price_source": "daily_close",
            "reason": f"need>={need}_closes",
        }
    spreads: list[float] = []
    for end in range(window + 1, len(arr) + 1):
        spr = roll_effective_spread(arr[:end], window=window)
        if spr is not None:
            spreads.append(spr)
    if not spreads:
        return {
            "spread": None,
            "spread_zscore": None,
            "gamma1_ok": False,
            "price_source": "daily_close",
            "reason": "gamma1_non_negative",
        }
    last = spreads[-1]
    hist = spreads[-median_lookback:]
    med = float(np.median(hist))
    if med <= 0:
        return {
            "spread": last,
            "spread_zscore": None,
            "gamma1_ok": True,
            "price_source": "daily_close",
            "reason": "median_non_positive",
        }
    mad = float(np.median(np.abs(np.asarray(hist) - med)))
    scale = 1.4826 * mad if mad > 1e-12 else float(np.std(hist, ddof=1) or 0.0)
    if scale <= 1e-12:
        z = 0.0
    else:
        z = (last - med) / scale
    return {
        "spread": last,
        "spread_zscore": z,
        "spread_median": med,
        "gamma1_ok": True,
        "price_source": "daily_close",
        "reason": "ok",
    }


def compute_maneuver_microstructure(df: pd.DataFrame | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "kyle_lambda": dict(KYLE_STATUS),
        "alpha003": dict(ALPHA003_STATUS),
    }
    if df is None or getattr(df, "empty", True):
        out["vwap_deviation"] = None
        out["vwap_deviation_rel"] = None
        out["spread_zscore"] = None
        return out
    o = _col(df, "open", "Open")
    h = _col(df, "high", "High")
    l = _col(df, "low", "Low")
    c = _col(df, "close", "Close")
    if o and h and l and c:
        valid = df[[o, h, l, c]].apply(pd.to_numeric, errors="coerce").dropna()
        if valid.empty:
            out["vwap_deviation"] = None
            out["vwap_deviation_rel"] = None
            out["vwap_source"] = "unavailable"
        else:
            last_row = valid.iloc[-1]
            last = {
                "open": last_row[o],
                "high": last_row[h],
                "low": last_row[l],
                "close": last_row[c],
            }
            out.update(alpha041_vwap_deviation(last))
    else:
        out["vwap_deviation"] = None
        out["vwap_deviation_rel"] = None
        out["vwap_source"] = "unavailable"
    if c:
        closes = []
        for x in df[c].tolist():
            try:
                fx = float(x)
            except (TypeError, ValueError):
                continue
            if math.isfinite(fx) and fx > 0:
                closes.append(fx)
        roll = roll_spread_zscore(closes)
        out["spread"] = roll.get("spread")
        out["spread_zscore"] = roll.get("spread_zscore")
        out["spread_median"] = roll.get("spread_median")
        out["roll_gamma1_ok"] = roll.get("gamma1_ok")
        out["roll_price_source"] = roll.get("price_source")
        out["roll_reason"] = roll.get("reason")
    else:
        out["spread_zscore"] = None
    return out


def vwap_component(vwap_deviation_rel: float | None) -> float | None:
    if vwap_deviation_rel is None:
        return None
    try:
        rel = float(vwap_deviation_rel)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(rel):
        return None
    return max(0.0, min(1.0, 0.5 + math.tanh(rel * 80.0) * 0.5))


def blend_composite(base: float, vwap_deviation_rel: float | None, *, weight: float = 0.12) -> float:
    micro = vwap_component(vwap_deviation_rel)
    if micro is None:
        return max(0.0, min(1.0, base))
    w = max(0.0, min(0.25, float(weight)))
    return max(0.0, min(1.0, (1.0 - w) * base + w * micro))


def roll_size_mult(spread_zscore: float | None) -> float:
    """Beside book_gate: shade size when implied spread is unusually wide. Never veto."""
    if spread_zscore is None:
        return 1.0
    try:
        z = float(spread_zscore)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(z):
        return 1.0
    if z >= 2.0:
        return 0.70
    if z >= 1.0:
        return 0.85
    return 1.0
