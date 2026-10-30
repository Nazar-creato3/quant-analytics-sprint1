"""Sequential residualization in the Two Sigma lens order (R10)."""
from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np

from app.services.factor_lens.names import FACTOR_ORDER


def _align(series: Mapping[str, Sequence[float]]) -> tuple[list[str], np.ndarray]:
    names = [name for name in FACTOR_ORDER if name in series and len(series[name]) > 0]
    if not names:
        return [], np.zeros((0, 0))
    length = min(len(series[name]) for name in names)
    matrix = np.column_stack([np.asarray(series[name][-length:], dtype=float) for name in names])
    return names, matrix


def sequential_orthogonalize(
    series: Mapping[str, Sequence[float]],
) -> dict[str, list[float]]:
    """Each next factor is the residual of OLS on previous residuals."""
    names, matrix = _align(series)
    if matrix.size == 0:
        return {}
    residuals = np.zeros_like(matrix)
    residuals[:, 0] = matrix[:, 0]
    for col in range(1, matrix.shape[1]):
        y = matrix[:, col]
        x = residuals[:, :col]
        xtx = x.T @ x
        try:
            coef = np.linalg.solve(xtx + 1e-12 * np.eye(col), x.T @ y)
        except np.linalg.LinAlgError:
            coef = np.zeros(col)
        residuals[:, col] = y - x @ coef
    return {name: [float(v) for v in residuals[:, i]] for i, name in enumerate(names)}


def pairwise_abs_corr(ortho: Mapping[str, Sequence[float]]) -> float:
    names = [name for name in FACTOR_ORDER if name in ortho]
    if len(names) < 2:
        return 0.0
    length = min(len(ortho[name]) for name in names)
    matrix = np.column_stack([np.asarray(ortho[name][-length:], dtype=float) for name in names])
    if matrix.shape[0] < 3:
        return 0.0
    corr = np.corrcoef(matrix, rowvar=False)
    off = np.abs(corr[np.triu_indices_from(corr, k=1)])
    return float(np.nanmax(off)) if off.size else 0.0
