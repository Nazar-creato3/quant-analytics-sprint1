"""Single risk book: equities + FX + rates proxies + vol. No paid SIP."""
from __future__ import annotations

from typing import Mapping

PROXY_SLEEVES: dict[str, str] = {
    "SPY": "equity",
    "TLT": "rates_long",
    "IEF": "rates_int",
    "UUP": "usd",
    "VIX": "vol",
    "VXX": "vol_etn",
    "EURUSD": "fx",
}


def _vol(returns: list[float]) -> float:
    n = len(returns)
    if n < 2:
        return 0.0
    mu = sum(returns) / n
    var = sum((x - mu) ** 2 for x in returns) / (n - 1)
    return var ** 0.5


def _corr(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n < 3:
        return 0.0
    xa, xb = a[-n:], b[-n:]
    ma = sum(xa) / n
    mb = sum(xb) / n
    cov = sum((xa[i] - ma) * (xb[i] - mb) for i in range(n)) / (n - 1)
    sa = _vol(xa)
    sb = _vol(xb)
    if sa <= 1e-12 or sb <= 1e-12:
        return 0.0
    return max(-1.0, min(1.0, cov / (sa * sb)))


def build_risk_book(
    histories: Mapping[str, list[float]],
    *,
    as_of: str | None = None,
) -> dict[str, object]:
    """histories: symbol → oldest-to-newest simple returns already known at as_of."""
    sleeves: dict[str, str] = {}
    vols: dict[str, float] = {}
    for sym, sleeve in PROXY_SLEEVES.items():
        series = list(histories.get(sym) or [])
        if len(series) < 3:
            continue
        sleeves[sym] = sleeve
        vols[sym] = round(_vol(series), 8)
    spy = list(histories.get("SPY") or [])
    betas: dict[str, float] = {}
    if len(spy) >= 3:
        spy_v = _vol(spy)
        for sym in sleeves:
            if sym == "SPY":
                betas[sym] = 1.0
                continue
            other = list(histories.get(sym) or [])
            if len(other) < 3 or spy_v <= 1e-12:
                continue
            betas[sym] = round(_corr(spy, other) * (_vol(other) / spy_v), 6)
    return {
        "as_of": as_of,
        "sleeves": sleeves,
        "ann_vol_proxy": vols,
        "beta_to_spy": betas,
        "note": "Proxies only (TLT/IEF/UUP/VIX/VXX). Not a VX futures curve.",
    }


def returns_as_of(
    bars: list[Mapping[str, float | str]],
    *,
    as_of: str | None,
) -> list[float]:
    """Simple returns from bars with date ≤ as_of. Future closes never enter the book."""
    from app.services.pit.clock import as_day

    cap = as_day(as_of) if as_of else None
    closes: list[float] = []
    for b in bars:
        day = as_day(b.get("date"))
        if cap and day and day > cap:
            continue
        try:
            closes.append(float(b["close"]))
        except (KeyError, TypeError, ValueError):
            continue
    out: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev:
            out.append(closes[i] / prev - 1.0)
    return out


def book_from_bars(
    bars_by_symbol: Mapping[str, list[Mapping[str, float | str]]],
    *,
    as_of: str,
) -> dict[str, object]:
    hist = {sym: returns_as_of(bars, as_of=as_of) for sym, bars in bars_by_symbol.items()}
    return build_risk_book(hist, as_of=as_of)
