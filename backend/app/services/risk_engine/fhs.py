"""Filtered historical simulation (EWMA) and control VaR methods.

FHS: standardize returns by conditional vol, resample the residual
distribution, scale by current sigma. RiskMetrics λ=0.94 is the default
stored in CONFIG_VERSION after the synthetic backtest in this package.

Sources: Barone-Adesi / Giannopoulos / Vosper (1999); RiskMetrics (1996).
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from app.services.quant_math.core import expected_shortfall, value_at_risk, VaRMethod

CONFIG_VERSION = "risk_engine.fhs.v1"
EWMA_LAMBDA = 0.94


def ewma_sigma(returns: Sequence[float], lam: float = EWMA_LAMBDA) -> list[float]:
    values = [float(r) for r in returns]
    if not values:
        return []
    var = values[0] ** 2
    out: list[float] = []
    for r in values:
        var = lam * var + (1.0 - lam) * r * r
        out.append(math.sqrt(max(var, 1e-18)))
    return out


def fhs_var_es(
    returns: Sequence[float],
    *,
    alpha: float = 0.05,
    lam: float = EWMA_LAMBDA,
) -> tuple[float, float]:
    values = [float(r) for r in returns]
    if len(values) < 2:
        return 0.0, 0.0
    sigmas = ewma_sigma(values, lam)
    z = [r / s for r, s in zip(values, sigmas)]
    sigma_now = sigmas[-1]
    scaled = [zi * sigma_now for zi in z]
    var = float(value_at_risk(scaled, 1.0 - alpha, method=VaRMethod.HISTORICAL))
    es = float(expected_shortfall(scaled, 1.0 - alpha, var))
    return max(0.0, var), max(0.0, es)


def historical_bundle(returns: Sequence[float]) -> dict[str, float]:
    values = [float(r) for r in returns]
    var95 = float(value_at_risk(values, 0.95, method=VaRMethod.HISTORICAL))
    var99 = float(value_at_risk(values, 0.99, method=VaRMethod.HISTORICAL))
    es975 = float(expected_shortfall(values, 0.975, max(var95, 0.0)))
    return {"var_95": var95, "var_99": var99, "es_975": es975}


def parametric_bundle(returns: Sequence[float]) -> dict[str, float]:
    values = [float(r) for r in returns]
    var95 = float(value_at_risk(values, 0.95, method=VaRMethod.PARAMETRIC))
    var99 = float(value_at_risk(values, 0.99, method=VaRMethod.PARAMETRIC))
    es975 = float(expected_shortfall(values, 0.975, max(var95, 0.0)))
    return {"var_95": max(0.0, var95), "var_99": max(0.0, var99), "es_975": max(0.0, es975)}


def monte_carlo_bundle(returns: Sequence[float], *, seed: int = 7, n: int = 4000) -> dict[str, float]:
    values = np.asarray(list(returns), dtype=float)
    mu = float(values.mean()) if values.size else 0.0
    sd = float(values.std(ddof=1)) if values.size > 1 else 0.0
    rng = np.random.default_rng(seed)
    sim = rng.normal(mu, max(sd, 1e-12), size=n)
    var95 = float(value_at_risk(sim.tolist(), 0.95, method=VaRMethod.HISTORICAL))
    var99 = float(value_at_risk(sim.tolist(), 0.99, method=VaRMethod.HISTORICAL))
    es975 = float(expected_shortfall(sim.tolist(), 0.975, max(var95, 0.0)))
    return {"var_95": var95, "var_99": var99, "es_975": es975}


def fhs_bundle(returns: Sequence[float]) -> dict[str, float]:
    var95, _ = fhs_var_es(returns, alpha=0.05)
    var99, _ = fhs_var_es(returns, alpha=0.01)
    _, es975 = fhs_var_es(returns, alpha=0.025)
    return {"var_95": var95, "var_99": var99, "es_975": es975}
