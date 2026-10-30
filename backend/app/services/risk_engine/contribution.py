"""Euler risk contribution (R2) and effective number of bets (R11).

Volatility: MRC_i = (Σw)_i / σ_p, RC_i = w_i · MRC_i, PRC_i = RC_i / σ_p.
CVaR/ES: RC_i = w_i · mean_{s∈T}(−r_{s,i}) on the tail T = {L_p ≥ VaR_α}.
ENB: exp(−Σ p_k ln p_k) on PCA risk shares (Meucci 2009).

Covariance is Ledoit–Wolf via sklearn.covariance.LedoitWolf (K4; skfolio is
added in K5, not here). Methodology: docs/research/R2-risk-contribution.md,
docs/research/R11-effective-bets.md, docs/methodology/risk.md.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

MIN_HISTORY_DAYS = 60
COV_WINDOW = 252


def _as_matrix(asset_returns: Sequence[Sequence[float]]) -> np.ndarray:
    matrix = np.asarray(asset_returns, dtype=float)
    if matrix.ndim != 2:
        raise ValueError("asset_returns must be T x N")
    return matrix


def _as_weights(weights: Sequence[float], n: int) -> np.ndarray:
    w = np.asarray(list(weights), dtype=float)
    if w.size != n:
        raise ValueError("weights length must match assets")
    total = float(w.sum())
    if abs(total) <= 1e-18:
        raise ValueError("weights sum to zero")
    return w / total


_COV_CACHE: dict[str, tuple[str, np.ndarray, str]] = {}


def _cov_cache_key(window: np.ndarray) -> str:
    from datetime import datetime, timezone
    from hashlib import sha1

    digest = sha1(window.tobytes()).hexdigest()[:16]
    day = datetime.now(timezone.utc).date().isoformat()
    return f"{day}:{window.shape}:{digest}"


def shrunk_covariance(asset_returns: Sequence[Sequence[float]]) -> tuple[np.ndarray, str]:
    """Ledoit–Wolf covariance on the last 252 rows. Cache key includes UTC date."""
    from sklearn.covariance import LedoitWolf

    matrix = _as_matrix(asset_returns)
    window = matrix[-min(len(matrix), COV_WINDOW) :]
    if window.shape[0] < 3:
        raise ValueError("need at least 3 observations for covariance")
    key = _cov_cache_key(window)
    hit = _COV_CACHE.get(key)
    if hit is not None:
        return hit[1].copy(), hit[2]
    cov = np.asarray(LedoitWolf().fit(window).covariance_, dtype=float)
    estimator = "sklearn.LedoitWolf"
    _COV_CACHE[key] = (key.split(":", 1)[0], cov, estimator)
    if len(_COV_CACHE) > 64:
        oldest = next(iter(_COV_CACHE))
        _COV_CACHE.pop(oldest, None)
    return cov, estimator


def vol_risk_contribution(
    weights: Sequence[float],
    cov: Sequence[Sequence[float]],
) -> dict[str, list[float] | float]:
    """Euler decomposition of portfolio volatility. Sum RC = σ_p (1e-9)."""
    sigma = np.asarray(cov, dtype=float)
    w = _as_weights(weights, sigma.shape[0])
    if sigma.shape[0] != sigma.shape[1]:
        raise ValueError("covariance must be square")
    var_p = float(w @ sigma @ w)
    sigma_p = float(np.sqrt(max(var_p, 0.0)))
    if sigma_p <= 1e-18:
        zeros = [0.0] * w.size
        return {
            "sigma": 0.0,
            "marginal": zeros,
            "component": zeros,
            "pct": [1.0] if w.size == 1 else zeros,
        }
    mrc = (sigma @ w) / sigma_p
    rc = w * mrc
    prc = rc / sigma_p
    return {
        "sigma": sigma_p,
        "marginal": [float(x) for x in mrc],
        "component": [float(x) for x in rc],
        "pct": [float(x) for x in prc],
    }


def es_risk_contribution(
    asset_returns: Sequence[Sequence[float]],
    weights: Sequence[float],
    *,
    alpha: float = 0.05,
) -> dict[str, list[float] | float]:
    """Historical ES contribution (R2). Sum RC = ES_α."""
    matrix = _as_matrix(asset_returns)
    w = _as_weights(weights, matrix.shape[1])
    losses = -(matrix @ w)
    if losses.size == 0:
        raise ValueError("empty return matrix")
    var = float(np.quantile(losses, 1.0 - alpha, method="linear"))
    tail = losses >= var - 1e-15
    if not np.any(tail):
        tail = losses >= np.max(losses)
    tail_losses = matrix[tail]
    # RC_i = w_i * mean_s(-r_{s,i})
    mean_tail = -np.mean(tail_losses, axis=0)
    rc = w * mean_tail
    es = float(np.mean(losses[tail]))
    s = float(rc.sum())
    if abs(s) > 1e-18 and abs(es) > 1e-18:
        rc = rc * (es / s)
    pct = (rc / es) if abs(es) > 1e-18 else np.zeros_like(rc)
    if w.size == 1 and abs(es) > 1e-18:
        pct = np.array([1.0])
        rc = np.array([es])
    return {
        "es": es,
        "var": var,
        "component": [float(x) for x in rc],
        "pct": [float(x) for x in pct],
        "tail_count": int(np.sum(tail)),
    }


def effective_number_of_bets(
    weights: Sequence[float],
    cov: Sequence[Sequence[float]],
) -> float | None:
    """Meucci ENB from PCA risk shares. None if covariance is degenerate."""
    sigma = np.asarray(cov, dtype=float)
    w = _as_weights(weights, sigma.shape[0])
    eigvals, eigvecs = np.linalg.eigh(sigma)
    eigvals = np.clip(eigvals, 0.0, None)
    exposures = eigvecs.T @ w
    shares = (exposures**2) * eigvals
    total = float(shares.sum())
    if total <= 1e-18:
        return None
    p = shares / total
    p = p[p > 1e-18]
    return float(np.exp(-np.sum(p * np.log(p))))


def history_flags(lengths: Sequence[int]) -> list[str | None]:
    return [
        "короткая история" if int(n) < MIN_HISTORY_DAYS else None for n in lengths
    ]


def attribute(
    asset_returns: Sequence[Sequence[float]],
    weights: Sequence[float],
    *,
    tickers: Sequence[str],
    lengths: Sequence[int] | None = None,
    alpha: float = 0.05,
) -> dict:
    """Per-name weight, vol share, CVaR share, history flag, plus ENB."""
    matrix = _as_matrix(asset_returns)
    w = _as_weights(weights, matrix.shape[1])
    names = [str(t).upper() for t in tickers]
    if len(names) != w.size:
        raise ValueError("tickers length must match assets")
    cov, estimator = shrunk_covariance(matrix)
    vol = vol_risk_contribution(w, cov)
    es = es_risk_contribution(matrix, w, alpha=alpha)
    flags = history_flags(lengths if lengths is not None else [matrix.shape[0]] * w.size)
    enb = effective_number_of_bets(w, cov)
    rows = []
    for i, name in enumerate(names):
        rows.append(
            {
                "ticker": name,
                "weight": float(w[i]),
                "vol_component": vol["component"][i],
                "pct_of_vol": vol["pct"][i],
                "es_component": es["component"][i],
                "pct_of_cvar": es["pct"][i],
                "history_note": flags[i],
            }
        )
    rows.sort(key=lambda r: float(r["pct_of_vol"]), reverse=True)
    return {
        "components": rows,
        "sigma": vol["sigma"],
        "es": es["es"],
        "enb": enb,
        "covariance_estimator": estimator,
        "methodology": "/methodology",
        "source": "оценка риска",
    }
