"""Projected QP / SOCP-lite: mean-variance + TE + CVaR + joint Kyle impact.

No cvxpy. Projected gradient onto the same hard set as optimizer constraints
(leftover is cash — never water-fill to 1).
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

from app.services.construction.tcm import kyle_impact_bps


def _impact_cost(w: np.ndarray, w0: np.ndarray, adv: np.ndarray, deploy_cap: float) -> float:
    if deploy_cap <= 0:
        return 0.0
    cost = 0.0
    for i in range(w.size):
        d_usd = abs(float(w[i] - w0[i])) * deploy_cap
        a = float(adv[i]) if i < adv.size else 0.0
        if d_usd <= 0:
            continue
        # round-trip impact in return units on the traded slice
        rt = 2.0 * kyle_impact_bps(d_usd, a) / 10_000.0
        cost += rt * (d_usd / deploy_cap)
    return cost


def _impact_grad(w: np.ndarray, w0: np.ndarray, adv: np.ndarray, deploy_cap: float) -> np.ndarray:
    """Finite-difference-free: d/dw_i of |Δw| * 2k sqrt(|Δusd|/ADV) / 1e4."""
    g = np.zeros_like(w)
    if deploy_cap <= 0:
        return g
    for i in range(w.size):
        dw = float(w[i] - w0[i])
        a = float(adv[i]) if i < adv.size else 0.0
        if a <= 0 or abs(dw) < 1e-12:
            continue
        # cost_i = 2k/1e4 * sqrt(|dw|*cap/ADV) * |dw|
        # d/d(dw) = 2k/1e4 * (1.5) * sign * sqrt(|dw|*cap/ADV)
        k = 10.0
        scale = 2.0 * k / 10_000.0
        g[i] = scale * 1.5 * np.sign(dw) * np.sqrt(abs(dw) * deploy_cap / a)
    return g


def qp_step(
    mu: np.ndarray,
    cov: np.ndarray,
    *,
    w0: np.ndarray,
    bench: np.ndarray | None,
    adv: np.ndarray,
    deploy_cap: float,
    risk_aversion: float = 4.0,
    te_aversion: float = 8.0,
    cvar_aversion: float = 2.0,
    impact_aversion: float = 1.0,
    cvar_alpha: float = 0.95,
    steps: int = 60,
    step: float = 0.15,
    hist_panel: np.ndarray | None = None,
) -> np.ndarray:
    n = mu.size
    if n == 0:
        return mu
    try:
        inv = np.linalg.pinv(cov + np.eye(n) * 1e-8)
        w = inv @ mu
    except np.linalg.LinAlgError:
        w = mu.copy()
    w = np.maximum(w, 0.0)
    if float(w.sum()) > 0:
        w = w / w.sum()
    wb = bench if bench is not None and bench.size == n else np.zeros(n)
    for _ in range(max(1, steps)):
        cov_w = cov @ w
        grad = -mu + float(risk_aversion) * cov_w
        active = w - wb
        grad = grad + float(te_aversion) * (cov @ active)
        port_vol = float(np.sqrt(max(float(w @ cov_w), 0.0)))
        if port_vol > 1e-12 and cvar_aversion > 0:
            # Gaussian ES gradient ∝ Σw / σ
            from app.services.construction.risk_model import gaussian_cvar

            es = gaussian_cvar(port_vol, alpha=cvar_alpha)
            grad = grad + float(cvar_aversion) * es / port_vol * cov_w
        if hist_panel is not None and hist_panel.shape[1] == n and hist_panel.shape[0] >= 20:
            port = hist_panel @ w
            q = float(np.quantile(port, 1.0 - cvar_alpha))
            tail = port <= q + 1e-12
            if np.any(tail):
                grad = grad + float(cvar_aversion) * (-hist_panel[tail].mean(axis=0))
        if impact_aversion > 0:
            grad = grad + float(impact_aversion) * _impact_grad(w, w0, adv, deploy_cap)
        w = np.maximum(w - step * grad, 0.0)
        tot = float(w.sum())
        if tot > 1.0:
            w = w / tot
    return w


def impact_objective(w: Sequence[float], w0: Sequence[float], adv: Sequence[float], deploy_cap: float) -> float:
    return _impact_cost(
        np.asarray(w, dtype=float),
        np.asarray(w0, dtype=float),
        np.asarray(list(adv) + [0.0] * max(0, len(w) - len(adv)), dtype=float)[: len(w)],
        deploy_cap,
    )
