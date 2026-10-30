"""Multi-asset FHS scenarios from the risk service (Prompt 09).

Each column is standardized by ewma_sigma and rescaled by the latest sigma.
Rows stay contemporaneous so historical dependence is kept.
Barone-Adesi, Giannopoulos, Vosper (1999); see risk_engine.fhs.
"""
from __future__ import annotations

import numpy as np

from app.services.target_portfolio.covariance import align_returns


def fhs_scenarios(series: list[tuple[float, ...]]) -> np.ndarray | None:
    panel = align_returns(series)
    if panel is None:
        return None
    from app.services.risk_engine.fhs import ewma_sigma

    columns: list[np.ndarray] = []
    for j in range(panel.shape[1]):
        values = panel[:, j].tolist()
        sigmas = ewma_sigma(values)
        if len(sigmas) != len(values):
            return None
        scaled = []
        sigma_now = sigmas[-1]
        for ret, sigma in zip(values, sigmas):
            if sigma <= 0:
                return None
            scaled.append((ret / sigma) * sigma_now)
        columns.append(np.asarray(scaled, dtype=float))
    out = np.column_stack(columns)
    if not np.isfinite(out).all():
        return None
    return out
