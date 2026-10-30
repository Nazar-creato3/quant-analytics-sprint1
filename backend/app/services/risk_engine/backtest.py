"""VaR/ES backtests: Kupiec, Christoffersen, Basel traffic light, Acerbi–Szekely Z1.

Kupiec (1995) unconditional coverage. Christoffersen (1998) independence
and conditional coverage. Basel 99%/250d traffic light. Acerbi–Szekely
(2014) Z1 unconditional ES test with a Monte Carlo p-value.
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np

CHI2_1_95 = 3.841458820694124
CHI2_2_95 = 5.991464547107979


def exception_flags(returns: Sequence[float], var_series: Sequence[float]) -> list[int]:
    return [1 if float(r) <= -float(v) else 0 for r, v in zip(returns, var_series)]


def kupiec_lr(exceptions: Sequence[int], alpha: float) -> float:
    n = len(exceptions)
    x = int(sum(exceptions))
    if n == 0 or not (0.0 < alpha < 1.0):
        return 0.0
    if x == 0:
        return -2.0 * n * math.log(1.0 - alpha)
    if x == n:
        return -2.0 * n * math.log(alpha)
    pi = x / n
    return -2.0 * (
        (n - x) * math.log(1.0 - alpha)
        + x * math.log(alpha)
        - (n - x) * math.log(1.0 - pi)
        - x * math.log(pi)
    )


def christoffersen_independence_lr(exceptions: Sequence[int]) -> float:
    n00 = n01 = n10 = n11 = 0
    for a, b in zip(exceptions[:-1], exceptions[1:]):
        if a == 0 and b == 0:
            n00 += 1
        elif a == 0 and b == 1:
            n01 += 1
        elif a == 1 and b == 0:
            n10 += 1
        else:
            n11 += 1
    n0 = n00 + n01
    n1 = n10 + n11
    n = n0 + n1
    if n == 0 or n0 == 0 or n1 == 0:
        return 0.0
    pi01 = n01 / n0
    pi11 = n11 / n1
    pi = (n01 + n11) / n

    def _ll(p: float, hits: int, total: int) -> float:
        if p <= 0.0 or p >= 1.0:
            return 0.0
        return hits * math.log(p) + (total - hits) * math.log(1.0 - p)

    ll_r = _ll(pi, n01 + n11, n)
    ll_u = _ll(pi01, n01, n0) + _ll(pi11, n11, n1)
    return -2.0 * (ll_r - ll_u)


def christoffersen_cc(exceptions: Sequence[int], alpha: float) -> float:
    return kupiec_lr(exceptions, alpha) + christoffersen_independence_lr(exceptions)


def reject_kupiec(exceptions: Sequence[int], alpha: float) -> bool:
    return kupiec_lr(exceptions, alpha) > CHI2_1_95


def reject_christoffersen(exceptions: Sequence[int], alpha: float) -> bool:
    return christoffersen_cc(exceptions, alpha) > CHI2_2_95


def traffic_light_99(exceptions_250: int) -> str:
    """Basel Committee traffic light for 99% VaR, 250 business days."""
    if exceptions_250 <= 4:
        return "green"
    if exceptions_250 <= 9:
        return "yellow"
    return "red"


def duration_lr(exceptions: Sequence[int], alpha: float) -> float:
    """Christoffersen–Pelletier style duration test (exponential vs geometric)."""
    gaps: list[int] = []
    last = -1
    for i, flag in enumerate(exceptions):
        if flag:
            gaps.append(i - last)
            last = i
    if len(gaps) < 2:
        return 0.0
    mean_d = sum(gaps) / len(gaps)
    expected = 1.0 / alpha
    # Likelihood-ratio vs geometric with success probability alpha.
    ll_h0 = sum(math.log(alpha) + (d - 1) * math.log(1.0 - alpha) for d in gaps)
    p = 1.0 / mean_d
    p = min(max(p, 1e-9), 1.0 - 1e-9)
    ll_h1 = sum(math.log(p) + (d - 1) * math.log(1.0 - p) for d in gaps)
    return -2.0 * (ll_h0 - ll_h1)


def acerbi_szekely_z1(
    returns: Sequence[float],
    var_series: Sequence[float],
    es_series: Sequence[float],
    *,
    alpha: float,
    seed: int = 11,
    sims: int = 400,
) -> dict[str, float | bool]:
    """Unconditional ES test Z1; p-value by simulation under i.i.d. residuals."""
    r = np.asarray(list(returns), dtype=float)
    v = np.asarray(list(var_series), dtype=float)
    e = np.asarray(list(es_series), dtype=float)
    hit = r <= -v
    if not hit.any() or float(e[hit].mean()) == 0.0:
        return {"z1": 0.0, "p_value": 1.0, "reject": False}
    z1 = float(np.mean((hit.astype(float) * r / np.maximum(e, 1e-12))) / alpha + 1.0)
    rng = np.random.default_rng(seed)
    sim_z = []
    for _ in range(sims):
        rr = rng.choice(r, size=len(r), replace=True)
        hh = rr <= -v
        if not hh.any():
            continue
        sim_z.append(float(np.mean((hh.astype(float) * rr / np.maximum(e, 1e-12))) / alpha + 1.0))
    if not sim_z:
        return {"z1": z1, "p_value": 1.0, "reject": False}
    p = float(np.mean(np.asarray(sim_z) <= z1))
    return {"z1": z1, "p_value": p, "reject": p < 0.05}


def rolling_var_series(returns: Sequence[float], *, window: int, alpha: float) -> list[float]:
    from app.services.risk_engine.fhs import fhs_var_es

    values = [float(x) for x in returns]
    out: list[float] = []
    for i in range(len(values)):
        start = max(0, i - window)
        hist = values[start:i] if i > 2 else values[: max(i, 2)]
        var, _ = fhs_var_es(hist if len(hist) >= 2 else values[:2], alpha=alpha)
        out.append(var)
    return out


def evaluate_series(returns: Sequence[float], *, window: int = 250) -> dict:
    from app.services.risk_engine.fhs import fhs_var_es

    values = [float(x) for x in returns]
    var95 = rolling_var_series(values, window=window, alpha=0.05)
    var99 = rolling_var_series(values, window=window, alpha=0.01)
    es975 = [fhs_var_es(values[max(0, i - window) : max(i, 2)], alpha=0.025)[1] for i in range(len(values))]
    ex95 = exception_flags(values, var95)
    ex99 = exception_flags(values, var99)
    last250 = ex99[-250:] if len(ex99) >= 250 else ex99
    kupiec_rej = reject_kupiec(ex95, 0.05) or reject_kupiec(ex99, 0.01)
    chris_rej = reject_christoffersen(ex95, 0.05)
    status = "beta" if kupiec_rej or chris_rej else "ready"
    return {
        "kupiec_lr_95": kupiec_lr(ex95, 0.05),
        "kupiec_lr_99": kupiec_lr(ex99, 0.01),
        "christoffersen_cc_95": christoffersen_cc(ex95, 0.05),
        "duration_lr_95": duration_lr(ex95, 0.05),
        "exceptions_95": int(sum(ex95)),
        "exceptions_99": int(sum(ex99)),
        "traffic_light": traffic_light_99(int(sum(last250))),
        "acerbi_z1": acerbi_szekely_z1(values, var95, es975, alpha=0.025),
        "status": status,
        "n": len(values),
    }
