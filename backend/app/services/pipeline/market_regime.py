"""Market regime from several liquid anchors — not a single SPY print."""
from __future__ import annotations

from typing import Any

import pandas as pd

from app.services.market_regime.service import label_from_closes

# Breadth + rates + fear, not one equity ETF.
REGIME_ANCHORS: tuple[str, ...] = ("SPY", "QQQ", "IWM", "EEM", "TLT", "VXX")
_REGIME_SCORE = {
    "trend_up": 1.0,
    "range": 0.0,
    "volatility": -0.25,
    "trend_down": -1.0,
    "crisis": -1.0,
    "insufficient": 0.0,
}


def _label_from_score(score: float, *, volatile_share: float) -> str:
    if volatile_share >= 0.5:
        return "volatility"
    if score >= 0.35:
        return "trend_up"
    if score <= -0.35:
        return "trend_down"
    return "range"


def compute_market_regime(market_data: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Vote across anchors + 1-day advance/decline of the fetched universe."""
    votes: dict[str, str] = {}
    numeric: list[float] = []
    volatile_n = 0
    for sym in REGIME_ANCHORS:
        df = market_data.get(sym)
        if df is None or getattr(df, "empty", True) or len(df) < 30:
            continue
        label = label_from_closes(df["close"].tolist(), ticker=sym)
        votes[sym] = label
        numeric.append(_REGIME_SCORE.get(label, 0.0))
        if label == "volatility":
            volatile_n += 1

    advances = 0
    declines = 0
    for df in market_data.values():
        if df is None or getattr(df, "empty", True) or "close" not in df.columns or len(df) < 2:
            continue
        closes = df["close"].dropna()
        if len(closes) < 2:
            continue
        delta = float(closes.iloc[-1]) - float(closes.iloc[-2])
        if delta > 0:
            advances += 1
        elif delta < 0:
            declines += 1
    breadth = 0.0
    counted = advances + declines
    if counted:
        breadth = (advances - declines) / counted

    vote_score = sum(numeric) / len(numeric) if numeric else 0.0
    blended = 0.65 * vote_score + 0.35 * breadth
    volatile_share = (volatile_n / len(numeric)) if numeric else 0.0
    label = _label_from_score(blended, volatile_share=volatile_share)
    if not numeric and counted:
        label = _label_from_score(breadth, volatile_share=0.0)
    elif not numeric and not counted:
        label = "insufficient"

    def _last_close(sym: str) -> float | None:
        df = market_data.get(sym)
        if df is None or getattr(df, "empty", True) or "close" not in getattr(df, "columns", []):
            return None
        series = df["close"].dropna()
        if series.empty:
            return None
        return float(series.iloc[-1])

    def _history(sym: str, n: int = 60) -> list[float]:
        df = market_data.get(sym)
        if df is None or getattr(df, "empty", True) or "close" not in getattr(df, "columns", []):
            return []
        return [float(x) for x in df["close"].dropna().tolist()[-n:]]

    # Level thresholds (VIX >= 32) only make sense for the index itself.  VXX is an
    # ETN *price* on a different scale, so it feeds the z-score history only.
    vix = _last_close("VIX") or _last_close("^VIX")
    dgs10 = _last_close("DGS10")
    dgs2 = _last_close("DGS2")
    curve = None
    if dgs10 is not None and dgs2 is not None:
        curve = dgs10 - dgs2
    # Credit stress threshold (>= 1.5) is for the HY OAS spread in percent.  HYG is a
    # fund price (~80 USD) and would read as permanent stress, blocking every trade.
    credit = _last_close("BAMLH0A0HYM2")
    from app.services.alpha.regime_gate import detect_regime

    gate = detect_regime(
        breadth=float(breadth),
        vix=vix,
        curve=curve,
        credit=credit,
        vix_history=_history("VIX") or _history("^VIX") or _history("VXX"),
        breadth_history=None,
    )

    return {
        "regime": label,
        "score": round(float(blended), 4),
        "breadth": round(float(breadth), 4),
        "advances": advances,
        "declines": declines,
        "anchor_votes": votes,
        "anchors_used": list(votes.keys()),
        "alpha_on": gate.alpha_on,
        "size_mult": gate.size_mult,
        "macro_veto": gate.macro_veto,
        "hmm_state": gate.hmm_state,
        "regime_gate": gate.label,
        "vix": gate.vix,
        "curve": gate.curve,
        "credit": gate.credit,
    }


def regime_to_macro_score(regime: str, *, breadth: float = 0.0, digest_macro: float | None = None) -> float:
    base = {
        "trend_up": 0.5,
        "trend_down": -0.5,
        "range": 0.0,
        "volatility": -0.2,
        "crisis": -0.5,
        "insufficient": 0.0,
        "bull": 0.5,
        "bear": -0.5,
        "sideways": 0.0,
        "volatile": -0.2,
        "unknown": 0.0,
    }.get(regime, 0.0)
    blended = 0.75 * base + 0.25 * max(-1.0, min(1.0, breadth))
    if digest_macro is not None:
        blended = 0.7 * blended + 0.3 * max(-1.0, min(1.0, float(digest_macro)))
    return max(-1.0, min(1.0, blended))
