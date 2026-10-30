"""Effective number of bets: Meucci 2009 PCA and Meucci–Santangelo–Deguest 2015."""
from __future__ import annotations

from typing import Sequence

import numpy as np
from scipy.linalg import sqrtm

from app.services.factor_lens.moments import ledoit_wolf_covariance


def _entropy_enb(shares: np.ndarray) -> float:
    total = float(shares.sum())
    if total <= 1e-18:
        return float("nan")
    p = shares / total
    p = p[p > 1e-18]
    return float(np.exp(-np.sum(p * np.log(p))))


def enb_pca(weights: Sequence[float], cov: Sequence[Sequence[float]]) -> float:
    sigma = np.asarray(cov, dtype=float)
    w = np.asarray(weights, dtype=float)
    if w.size != sigma.shape[0]:
        raise ValueError("weights/cov size")
    eigvals, eigvecs = np.linalg.eigh(sigma)
    eigvals = np.clip(eigvals, 0.0, None)
    exposures = eigvecs.T @ w
    return _entropy_enb((exposures**2) * eigvals)


def minimum_torsion_matrix(cov: Sequence[Sequence[float]]) -> np.ndarray:
    """Uncorrelate while staying near the original assets (2015 iterative sqrtm)."""
    sigma = 0.5 * (np.asarray(cov, dtype=float) + np.asarray(cov, dtype=float).T)
    n = sigma.shape[0]
    vol = np.sqrt(np.clip(np.diag(sigma), 1e-18, None))
    corr = sigma / np.outer(vol, vol)
    np.fill_diagonal(corr, 1.0)
    d = np.ones(n)
    u = np.eye(n)
    for _ in range(80):
        scaled = corr * np.outer(d, d)
        u = np.real(sqrtm(np.clip(scaled, -1e6, 1e6)))
        d_new = np.real(np.diag(u))
        if float(np.max(np.abs(d_new - d))) < 1e-12:
            d = d_new
            break
        d = d_new
    try:
        u_inv = np.linalg.inv(u)
    except np.linalg.LinAlgError:
        u_inv = np.linalg.pinv(u)
    return np.diag(1.0 / vol) @ u_inv @ np.diag(vol)


def enb_min_torsion(weights: Sequence[float], cov: Sequence[Sequence[float]]) -> float:
    t = minimum_torsion_matrix(cov)
    sigma = np.asarray(cov, dtype=float)
    w = np.asarray(weights, dtype=float)
    factor_cov = t @ sigma @ t.T
    b = t @ w
    vols2 = np.clip(np.diag(factor_cov), 0.0, None)
    return _entropy_enb((b**2) * vols2)


def diversification_ratio(weights: Sequence[float], cov: Sequence[Sequence[float]]) -> float:
    """Choueifaty–Coignard: Σ w_i σ_i / σ_p."""
    sigma = np.asarray(cov, dtype=float)
    w = np.asarray(weights, dtype=float)
    vols = np.sqrt(np.clip(np.diag(sigma), 0.0, None))
    port = float(np.sqrt(max(w @ sigma @ w, 0.0)))
    if port <= 1e-18:
        return float("nan")
    return float((w * vols).sum() / port)


def enb_from_returns(asset_returns: Sequence[Sequence[float]], weights: Sequence[float]) -> dict[str, float | None]:
    matrix = np.asarray(asset_returns, dtype=float)
    cov = ledoit_wolf_covariance(matrix)
    pca = enb_pca(weights, cov)
    mt = enb_min_torsion(weights, cov)
    dr = diversification_ratio(weights, cov)

    def _clean(value: float) -> float | None:
        return None if value != value else float(value)

    return {"enb_pca": _clean(pca), "enb_min_torsion": _clean(mt), "diversification_ratio": _clean(dr)}
