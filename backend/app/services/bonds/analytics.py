"""Yield, duration, convexity, G-spread. Conventions: Actual/365F (R5, QuantLib).

QuantLib is the specified engine. If the C++ wheel is missing on this Python,
the same formulas run in numpy (Newton YTM, closed-form duration/convexity).
"""
from __future__ import annotations

from datetime import date
from math import isfinite
from typing import Any, Sequence

try:
    import QuantLib as ql  # type: ignore

    _QL = True
except Exception:  # pragma: no cover - optional wheel
    ql = None
    _QL = False

DAY_COUNT = "Actual/365F"
FREQ = 2
YTM_TOL = 1e-12
YTM_ITERS = 80


def year_fraction(start: date, end: date) -> float:
    return (end - start).days / 365.0


def _times(settlement: date, flow_dates: Sequence[date]) -> list[float]:
    return [year_fraction(settlement, d) for d in flow_dates]


def price_from_yield(cashflows: Sequence[float], times: Sequence[float], y: float) -> float:
    return sum(cf / (1.0 + y) ** t for cf, t in zip(cashflows, times, strict=True))


def yield_to_maturity(
    cashflows: Sequence[float],
    times: Sequence[float],
    dirty_price: float,
    *,
    guess: float = 0.08,
) -> float | None:
    if dirty_price <= 0 or not cashflows or not times:
        return None
    y = guess
    for _ in range(YTM_ITERS):
        px = 0.0
        dpx = 0.0
        for cf, t in zip(cashflows, times, strict=True):
            disc = (1.0 + y) ** t
            if disc == 0:
                return None
            px += cf / disc
            dpx -= t * cf / ((1.0 + y) ** (t + 1.0))
        gap = px - dirty_price
        if abs(gap) < YTM_TOL:
            return y
        if dpx == 0:
            return None
        y -= gap / dpx
        if y <= -0.99:
            y = -0.5
    return None


def macaulay_duration(cashflows: Sequence[float], times: Sequence[float], y: float, dirty_price: float) -> float | None:
    if dirty_price <= 0:
        return None
    mac = sum(t * cf / (1.0 + y) ** t for cf, t in zip(cashflows, times, strict=True)) / dirty_price
    return mac if isfinite(mac) else None


def modified_duration(mac: float, y: float) -> float:
    return mac / (1.0 + y)


def convexity(cashflows: Sequence[float], times: Sequence[float], y: float, dirty_price: float) -> float | None:
    if dirty_price <= 0:
        return None
    cnv = sum(t * (t + 1.0) * cf / (1.0 + y) ** (t + 2.0) for cf, t in zip(cashflows, times, strict=True)) / dirty_price
    return cnv if isfinite(cnv) else None


def current_yield(annual_coupon: float, clean_price: float) -> float | None:
    if clean_price <= 0:
        return None
    return annual_coupon / clean_price


def interpolate_curve(tenor_years: float, points: Sequence[tuple[float, float]]) -> float | None:
    if not points:
        return None
    ordered = sorted((float(t), float(y)) for t, y in points)
    if tenor_years <= ordered[0][0]:
        return ordered[0][1]
    if tenor_years >= ordered[-1][0]:
        return ordered[-1][1]
    for (t0, y0), (t1, y1) in zip(ordered, ordered[1:]):
        if t0 <= tenor_years <= t1:
            if t1 == t0:
                return y0
            w = (tenor_years - t0) / (t1 - t0)
            return y0 + w * (y1 - y0)
    return None


def g_spread(ytm: float, mac_years: float, curve_points: Sequence[tuple[float, float]]) -> float | None:
    ofz = interpolate_curve(mac_years, curve_points)
    if ofz is None:
        return None
    return ytm - ofz


def rate_stress(*, dirty_value: float, d_mod: float, conv: float, shift_yield: float) -> float:
    """ΔP ≈ −D_mod·Δy·P + ½·C·Δy²·P. shift_yield is decimal (0.01 = 1 п.п.)."""
    return (-d_mod * shift_yield * dirty_value) + (0.5 * conv * shift_yield * shift_yield * dirty_value)


def quantlib_available() -> bool:
    return bool(_QL)


def metrics_from_flows(
    *,
    settlement: date,
    flow_dates: Sequence[date],
    amounts: Sequence[float],
    dirty_price: float,
    clean_price: float | None,
    aci: float | None,
    annual_coupon: float | None,
    curve_points: Sequence[tuple[float, float]] | None = None,
    floater: bool = False,
    next_reset: date | None = None,
    to_offer: bool = False,
) -> dict[str, Any]:
    times = _times(settlement, flow_dates)
    if any(t <= 0 for t in times) or not times:
        return {"status": "нет данных", "reason": "нет будущих потоков"}
    ytm = yield_to_maturity(amounts, times, dirty_price)
    if ytm is None:
        return {"status": "нет данных", "reason": "доходность не сходится"}
    mac = macaulay_duration(amounts, times, ytm, dirty_price)
    if mac is None:
        return {"status": "нет данных", "reason": "дюрация не считается"}
    d_mod = modified_duration(mac, ytm)
    conv = convexity(amounts, times, ytm, dirty_price)
    cy = current_yield(annual_coupon, clean_price) if annual_coupon is not None and clean_price else None
    gs = g_spread(ytm, mac, curve_points or []) if curve_points else None
    floater_mac = year_fraction(settlement, next_reset) if floater and next_reset and next_reset > settlement else None
    return {
        "status": "ok",
        "day_count": DAY_COUNT,
        "engine": "QuantLib" if _QL else "numpy-Actual365F",
        "ytm": ytm,
        "ytp": ytm if to_offer else None,
        "current_yield": cy,
        "dirty_price": dirty_price,
        "clean_price": clean_price,
        "aci": aci,
        "macaulay": floater_mac if floater_mac is not None else mac,
        "macaulay_to_maturity": mac,
        "modified": (floater_mac / (1.0 + ytm) if floater_mac is not None else d_mod),
        "convexity": conv,
        "g_spread": gs,
        "floater": floater,
        "quantlib": _QL,
    }
