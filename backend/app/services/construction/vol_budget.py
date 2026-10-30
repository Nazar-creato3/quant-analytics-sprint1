"""Book-level vol target: Turtle N scaled to the *book*, not only per-trade ATR."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from app.services.quant_desk.vol_target import turtle_unit_usd


@dataclass(frozen=True, slots=True)
class NameRisk:
    symbol: str
    weight: float
    price: float
    atr: float
    vol_ann: float = 0.0


@dataclass(frozen=True, slots=True)
class VolBudget:
    target_ann: float
    forecast_ann: float
    scale: float
    units: float
    notes: str


def forecast_book_vol(weights: Sequence[float], vols: Sequence[float], corr: float = 0.35) -> float:
    w = np.asarray([float(x) for x in weights], dtype=float)
    v = np.asarray([max(float(x), 1e-6) for x in vols], dtype=float)
    if w.size == 0:
        return 0.0
    rho = min(1.0, max(-1.0, float(corr)))
    cov = np.outer(v, v) * rho
    np.fill_diagonal(cov, v**2)
    var = float(w @ cov @ w)
    return float(np.sqrt(max(var, 0.0)))


def turtle_book_units(equity_usd: float, names: Sequence[NameRisk], *, risk_frac: float = 0.01) -> float:
    """How many Turtle units the current book already consumes (sum w*notional / unit)."""
    used = 0.0
    for n in names:
        unit = turtle_unit_usd(equity_usd=equity_usd, price=n.price, atr=n.atr, risk_frac=risk_frac)
        if unit <= 0:
            continue
        used += abs(n.weight) * equity_usd / unit
    return used


def scale_book_to_vol_target(
    weights: Sequence[float],
    names: Sequence[NameRisk],
    *,
    equity_usd: float,
    target_ann: float = 0.12,
    corr: float = 0.35,
    max_scale: float = 1.0,
    min_scale: float = 0.0,
    cov: np.ndarray | None = None,
) -> tuple[list[float], VolBudget]:
    vols = [n.vol_ann if n.vol_ann > 0 else (n.atr / n.price) * np.sqrt(252.0) if n.price > 0 else 0.2 for n in names]
    w = np.asarray([float(x) for x in weights], dtype=float)
    if cov is not None and cov.shape[0] == w.size:
        forecast = float(np.sqrt(max(float(w @ cov @ w), 0.0)))
        note = "risk_book_sigma+turtle_n"
    else:
        forecast = forecast_book_vol(weights, vols, corr=corr)
        note = "book_vol_target+turtle_n"
    if forecast <= 1e-8 or target_ann <= 0:
        scale = 1.0
    else:
        scale = min(max_scale, max(min_scale, target_ann / forecast))
    # Also cap by Turtle book units: more than ~4 units of book risk is a full sleeve.
    units = turtle_book_units(equity_usd, names)
    if units > 4.0:
        scale = min(scale, 4.0 / units)
    scaled = [float(w) * scale for w in weights]
    return scaled, VolBudget(
        target_ann=target_ann,
        forecast_ann=round(forecast, 6),
        scale=round(scale, 6),
        units=round(units, 4),
        notes=note,
    )
