"""Euler variance shares of orthogonal factors plus idiosyncratic risk (R2)."""
from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np

from app.services.factor_lens.names import FACTOR_ORDER


def factor_variance_shares(
    betas: Mapping[str, float],
    factor_returns: Mapping[str, Sequence[float]],
    portfolio_returns: Sequence[float],
) -> dict[str, float | None]:
    names = [n for n in FACTOR_ORDER if n in betas and n in factor_returns and betas[n] == betas[n]]
    if not names or len(portfolio_returns) < 10:
        return {n: None for n in FACTOR_ORDER} | {"idiosyncratic": None}
    length = min(len(portfolio_returns), *[len(factor_returns[n]) for n in names])
    y = np.asarray(portfolio_returns[-length:], dtype=float)
    f = np.column_stack([np.asarray(factor_returns[n][-length:], dtype=float) for n in names])
    b = np.asarray([betas[n] for n in names], dtype=float)
    explained = f @ b
    residual = y - explained
    var_y = float(np.var(y, ddof=1))
    if var_y <= 1e-18:
        return {n: None for n in FACTOR_ORDER} | {"idiosyncratic": None}
    # Euler on factor covariance: RC_k = b_k * (Σ_f b)_k / var_y
    cov_f = np.cov(f, rowvar=False, ddof=1)
    if cov_f.ndim == 0:
        cov_f = np.array([[float(cov_f)]])
    sigma_b = cov_f @ b
    shares = {n: float(b[i] * sigma_b[i] / var_y) for i, n in enumerate(names)}
    idio = float(np.var(residual, ddof=1) / var_y)
    raw_sum = sum(shares.values()) + idio
    if abs(raw_sum) > 1e-12:
        scale = 1.0 / raw_sum
        shares = {k: v * scale for k, v in shares.items()}
        idio *= scale
    out: dict[str, float | None] = {n: None for n in FACTOR_ORDER}
    out.update(shares)
    out["idiosyncratic"] = idio
    return out
