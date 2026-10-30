"""Book VaR/ES: historical + parametric on free returns. Positive = loss."""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Mapping, Sequence

import numpy as np

from app.services.risk_engine.fhs import fhs_var_es
from app.services.risk_engine.shadow import shadow_compare


def _norm_ppf(p: float) -> float:
    """Acklam inverse-normal; p in (0,1)."""
    if p <= 0.0:
        return -8.0
    if p >= 1.0:
        return 8.0
    a = (-3.969683028665376e1, 2.209460984351305e2, -2.759285104469687e2, 1.383577518672690e2, -3.066479806614716e1, 2.506628277459239)
    b = (-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2, 6.680131188771972e1, -1.328068155288572e1)
    c = (-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783)
    d = (7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996, 3.754408661907416)
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = sqrt(-2 * np.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p > phigh:
        q = sqrt(-2 * np.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )


def _norm_pdf(z: float) -> float:
    return float(np.exp(-0.5 * z * z) / sqrt(2.0 * np.pi))


@dataclass(frozen=True, slots=True)
class BookRisk:
    var95_hist: float | None
    var99_hist: float | None
    es95_hist: float | None
    var95_param: float
    var99_param: float
    es95_param: float
    port_vol: float
    n: int


def portfolio_returns(
    weights: Sequence[float],
    hist: Mapping[str, Sequence[float]],
    symbols: Sequence[str],
) -> np.ndarray:
    cols: list[np.ndarray] = []
    w: list[float] = []
    for i, sym in enumerate(symbols):
        s = [float(x) for x in (hist.get(sym) or []) if x is not None]
        if len(s) < 5:
            continue
        cols.append(np.asarray(s, dtype=float))
        w.append(float(weights[i]) if i < len(weights) else 0.0)
    if not cols:
        return np.asarray([])
    t = min(c.size for c in cols)
    R = np.column_stack([c[-t:] for c in cols])
    ww = np.asarray(w, dtype=float)
    return R @ ww


def parametric_var_es(port_vol: float, *, mu: float = 0.0) -> tuple[float, float, float]:
    z95 = abs(_norm_ppf(0.05))
    z99 = abs(_norm_ppf(0.01))
    var95 = max(0.0, z95 * port_vol - mu)
    var99 = max(0.0, z99 * port_vol - mu)
    es95 = max(0.0, port_vol * _norm_pdf(z95) / 0.05 - mu)
    return var95, var99, es95


def book_risk(
    weights: Sequence[float],
    symbols: Sequence[str],
    *,
    hist: Mapping[str, Sequence[float]] | None = None,
    cov: np.ndarray | None = None,
) -> BookRisk:
    w = np.asarray([float(x) for x in weights], dtype=float)
    port_vol = 0.0
    if cov is not None and cov.shape[0] == w.size and w.size:
        port_vol = float(np.sqrt(max(float(w @ cov @ w), 0.0)))
    elif hist:
        pr = portfolio_returns(weights, hist, symbols)
        if pr.size >= 5:
            port_vol = float(np.std(pr, ddof=1))
    p95, p99, pes = parametric_var_es(port_vol)
    h95 = h99 = hes = None
    n = 0
    if hist:
        pr = portfolio_returns(weights, hist, symbols)
        n = int(pr.size)
        if n >= 40:
            values = pr.tolist()
            shadow_compare(values)
            h95, hes = fhs_var_es(values, alpha=0.05)
            h99, _ = fhs_var_es(values, alpha=0.01)
        elif n >= 10:
            # honest small-sample hist: empirical quantile, flagged via n
            q05 = float(np.percentile(pr, 5))
            q01 = float(np.percentile(pr, 1))
            tail = pr[pr <= q05]
            h95 = max(0.0, -q05)
            h99 = max(0.0, -q01, h95)
            hes = max(0.0, -float(tail.mean()) if tail.size else h95)
    return BookRisk(
        var95_hist=h95,
        var99_hist=h99,
        es95_hist=hes,
        var95_param=round(p95, 8),
        var99_param=round(p99, 8),
        es95_param=round(pes, 8),
        port_vol=round(port_vol, 8),
        n=n,
    )
