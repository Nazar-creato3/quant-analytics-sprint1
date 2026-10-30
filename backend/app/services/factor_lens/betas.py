"""Ridge betas with shrink toward the industry mean (R10)."""
from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np

from app.services.factor_lens.names import BETA_WINDOW, INDUSTRY_SHRINK, RIDGE_LAMBDA


def ridge_betas(
    asset: Sequence[float],
    factors: Mapping[str, Sequence[float]],
    *,
    names: Sequence[str],
    ridge: float = RIDGE_LAMBDA,
) -> tuple[dict[str, float], float]:
    length = min([len(asset), *[len(factors[n]) for n in names if n in factors]])
    if length < max(20, len(names) + 5):
        return {n: float("nan") for n in names}, float("nan")
    y = np.asarray(asset[-length:], dtype=float)
    x = np.column_stack([np.asarray(factors[n][-length:], dtype=float) for n in names])
    xtx = x.T @ x + ridge * np.eye(x.shape[1])
    try:
        coef = np.linalg.solve(xtx, x.T @ y)
    except np.linalg.LinAlgError:
        return {n: float("nan") for n in names}, float("nan")
    fitted = x @ coef
    ss_res = float(np.sum((y - fitted) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-18 else float("nan")
    return {n: float(c) for n, c in zip(names, coef, strict=True)}, r2


def shrink_to_industry(
    betas: Mapping[str, float],
    industry_mean: Mapping[str, float] | None,
    *,
    alpha: float = INDUSTRY_SHRINK,
) -> dict[str, float]:
    if not industry_mean:
        return dict(betas)
    out = {}
    for name, value in betas.items():
        mean = industry_mean.get(name)
        if value != value or mean is None or mean != mean:
            out[name] = value
        else:
            out[name] = (1.0 - alpha) * value + alpha * mean
    return out


def window_slice(series: Sequence[float], window: int = BETA_WINDOW) -> list[float]:
    return list(series[-window:]) if len(series) > window else list(series)
