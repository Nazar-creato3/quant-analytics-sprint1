"""Free Barra-shaped book: LW shrinkage + statistical factors + idio + Bayesian prior.

No vendor factor library. Factors are built from the return panel we already have:
market (CS mean), sector residuals, optional size. Σ = (1-τ) S_LW + τ (B F B' + D).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np


@dataclass(frozen=True, slots=True)
class RiskBook:
    cov: np.ndarray
    factor_cov: np.ndarray
    loadings: np.ndarray
    idio_var: np.ndarray
    shrink: float
    prior_w: float
    factor_names: tuple[str, ...]
    notes: tuple[str, ...]


def _panel(
    hist: Mapping[str, Sequence[float]] | None,
    names: Sequence[str],
    min_t: int = 20,
) -> np.ndarray | None:
    if not hist:
        return None
    cols: list[np.ndarray] = []
    for name in names:
        s = [float(x) for x in (hist.get(name) or []) if x is not None]
        if len(s) < min_t:
            return None
        cols.append(np.asarray(s, dtype=float))
    t = min(c.size for c in cols)
    if t < min_t:
        return None
    return np.column_stack([c[-t:] for c in cols])


def ledoit_wolf_const_corr(R: np.ndarray) -> tuple[np.ndarray, float]:
    """Ledoit–Wolf shrink sample cov toward constant-correlation target."""
    t, n = R.shape
    if t < 3 or n < 1:
        return np.eye(n) * 1e-4, 1.0
    x = R - R.mean(axis=0, keepdims=True)
    s = (x.T @ x) / t
    var = np.clip(np.diag(s), 1e-12, None)
    sd = np.sqrt(var)
    outer = np.outer(sd, sd)
    corr = np.divide(s, outer, out=np.eye(n), where=outer > 0)
    np.fill_diagonal(corr, 1.0)
    off = corr[np.triu_indices(n, 1)]
    rho = float(np.mean(off)) if off.size else 0.0
    rho = min(0.99, max(-0.99, rho))
    target_corr = np.full((n, n), rho)
    np.fill_diagonal(target_corr, 1.0)
    f = target_corr * outer
    # LW intensity (simplified, Ledoit-Wolf 2004 const-corr)
    d = s - f
    num = 0.0
    for k in range(t):
        rk = x[k : k + 1].T @ x[k : k + 1]
        num += float(np.sum((rk - s) ** 2))
    num /= t
    den = float(np.sum(d**2))
    alpha = 1.0 if den <= 1e-18 else min(1.0, max(0.0, num / den / t))
    return (1.0 - alpha) * s + alpha * f, alpha


def _factor_panel(
    R: np.ndarray,
    sectors: Sequence[str],
    size: Sequence[float] | None,
) -> tuple[np.ndarray, tuple[str, ...]]:
    """Statistical factors: market + sector (k-1) + size if dispersion exists."""
    t, n = R.shape
    mkt = R.mean(axis=1, keepdims=True)
    cols = [mkt]
    names = ["market"]
    uniq = []
    for s in sectors:
        key = (s or "UNK").upper()
        if key not in uniq:
            uniq.append(key)
    if len(uniq) >= 2:
        for sec in uniq[:-1]:
            mask = np.array([(s or "UNK").upper() == sec for s in sectors], dtype=float)
            if mask.sum() <= 0:
                continue
            sec_r = (R * mask).sum(axis=1, keepdims=True) / mask.sum()
            cols.append(sec_r - mkt)
            names.append(f"sec:{sec}")
    if size and len(size) == n:
        z = np.asarray([float(x) for x in size], dtype=float)
        if float(np.std(z)) > 1e-12:
            z = (z - z.mean()) / (z.std() + 1e-12)
            cols.append((R * z).mean(axis=1, keepdims=True))
            names.append("size")
    F = np.hstack(cols)
    return F, tuple(names)


def factor_implied(
    R: np.ndarray, sectors: Sequence[str], size: Sequence[float] | None
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, tuple[str, ...]]:
    """Σ_f = B Fcov B' + D. Loadings from OLS of each name on statistical factors."""
    F, fnames = _factor_panel(R, sectors, size)
    k = F.shape[1]
    gram = F.T @ F + np.eye(k) * 1e-8
    try:
        b = np.linalg.solve(gram, F.T @ R)
    except np.linalg.LinAlgError:
        b = np.linalg.pinv(gram) @ (F.T @ R)
    resid = R - F @ b
    idio = np.clip(np.var(resid, axis=0, ddof=1), 1e-8, None)
    fcov = np.cov(F, rowvar=False)
    if np.ndim(fcov) == 0:
        fcov = np.array([[float(fcov)]])
    sigma = b.T @ fcov @ b + np.diag(idio)
    return sigma, b.T, idio, fcov, fnames


def blend_cov(
    names: Sequence[str],
    vols: Sequence[float],
    *,
    hist: Mapping[str, Sequence[float]] | None = None,
    sectors: Sequence[str] | None = None,
    size: Sequence[float] | None = None,
    prior_w: float = 0.35,
) -> RiskBook:
    n = len(names)
    notes: list[str] = []
    diag = np.diag(np.asarray([max(float(v), 1e-4) for v in vols], dtype=float) ** 2)
    if n == 0:
        return RiskBook(np.zeros((0, 0)), np.zeros((0, 0)), np.zeros((0, 0)), np.zeros(0), 1.0, prior_w, (), ("empty",))
    R = _panel(hist, names)
    if R is None:
        notes.append("diag_vol_prior")
        return RiskBook(diag, np.zeros((0, 0)), np.zeros((n, 0)), np.diag(diag), 1.0, 1.0, (), tuple(notes))
    s_lw, shrink = ledoit_wolf_const_corr(R)
    secs = list(sectors or ["UNK"] * n)
    try:
        s_f, loads, idio, fcov, fnames = factor_implied(R, secs, size)
        notes.append("factor_bfb_d")
    except Exception:
        s_f, loads, idio, fcov, fnames = diag.copy(), np.zeros((n, 0)), np.diag(diag), np.zeros((0, 0)), ()
        notes.append("factor_failed")
    tau = min(0.85, max(0.0, float(prior_w)))
    cov = (1.0 - tau) * s_lw + tau * s_f
    cov = 0.5 * (cov + cov.T) + np.eye(n) * 1e-8
    notes.append(f"lw_shrink={shrink:.3f}")
    notes.append(f"bayes_tau={tau:.2f}")
    return RiskBook(
        cov=cov,
        factor_cov=fcov,
        loadings=loads,
        idio_var=idio,
        shrink=float(shrink),
        prior_w=tau,
        factor_names=fnames,
        notes=tuple(notes),
    )


def decompose_book(weights: Sequence[float], book: RiskBook) -> dict[str, float]:
    w = np.asarray([float(x) for x in weights], dtype=float)
    if w.size == 0 or book.cov.size == 0:
        return {"port_var": 0.0, "port_vol": 0.0, "factor_var": 0.0, "idio_var": 0.0}
    port_var = float(w @ book.cov @ w)
    factor_var = 0.0
    if book.loadings.size and book.loadings.shape[0] == w.size:
        # systematic ≈ w' B F B' w = (B'w)' F (B'w) but we only stored idio
        idio = float((w**2) @ book.idio_var) if book.idio_var.size == w.size else 0.0
        factor_var = max(0.0, port_var - idio)
    else:
        idio = port_var
    return {
        "port_var": port_var,
        "port_vol": float(np.sqrt(max(port_var, 0.0))),
        "factor_var": factor_var,
        "idio_var": idio,
    }


def tracking_error(weights: Sequence[float], bench: Sequence[float], cov: np.ndarray) -> float:
    w = np.asarray([float(x) for x in weights], dtype=float)
    b = np.asarray([float(x) for x in bench], dtype=float)
    if w.size != b.size or cov.shape[0] != w.size:
        return 0.0
    a = w - b
    return float(np.sqrt(max(float(a @ cov @ a), 0.0)))


def gaussian_cvar(port_vol: float, *, alpha: float = 0.95, z: float = 1.64485) -> float:
    """ES under N(0,σ): φ(z)/(1-α) * σ. Positive number = loss units."""
    from math import exp, pi, sqrt

    if port_vol <= 0:
        return 0.0
    phi = exp(-0.5 * z * z) / sqrt(2.0 * pi)
    return float(port_vol * phi / max(1e-8, 1.0 - alpha))
