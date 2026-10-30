"""Euler risk allocation: component and marginal VaR/ES.

Property: sum of component VaR equals portfolio VaR (renormalized after
finite-difference marginals). Methodology: Tasche / McNeil–Frey–Embrechts.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

from app.services.risk_engine.fhs import fhs_var_es


def _portfolio_returns(matrix: np.ndarray, weights: np.ndarray) -> list[float]:
    return (matrix @ weights).astype(float).tolist()


def euler_allocate(
    asset_returns: Sequence[Sequence[float]],
    weights: Sequence[float],
    *,
    alpha: float = 0.05,
    eps: float = 1e-4,
) -> dict[str, list[float] | float]:
    matrix = np.asarray(asset_returns, dtype=float)
    if matrix.ndim != 2:
        raise ValueError("asset_returns must be T x N")
    w = np.asarray(list(weights), dtype=float)
    if w.size != matrix.shape[1]:
        raise ValueError("weights length must match assets")
    if abs(float(w.sum())) > 1e-12:
        w = w / w.sum()
    base_r = _portfolio_returns(matrix, w)
    var_p, es_p = fhs_var_es(base_r, alpha=alpha)
    marginal_var: list[float] = []
    marginal_es: list[float] = []
    for i in range(w.size):
        bumped = w.copy()
        bumped[i] += eps
        vr, er = fhs_var_es(_portfolio_returns(matrix, bumped), alpha=alpha)
        marginal_var.append((vr - var_p) / eps)
        marginal_es.append((er - es_p) / eps)
    comp_var = [float(w[i] * marginal_var[i]) for i in range(w.size)]
    comp_es = [float(w[i] * marginal_es[i]) for i in range(w.size)]
    s_var = sum(comp_var)
    s_es = sum(comp_es)
    if abs(s_var) > 1e-12:
        scale = var_p / s_var
        comp_var = [c * scale for c in comp_var]
    if abs(s_es) > 1e-12:
        scale_e = es_p / s_es
        comp_es = [c * scale_e for c in comp_es]
    return {
        "portfolio_var": var_p,
        "portfolio_es": es_p,
        "component_var": comp_var,
        "component_es": comp_es,
        "marginal_var": marginal_var,
        "marginal_es": marginal_es,
    }
