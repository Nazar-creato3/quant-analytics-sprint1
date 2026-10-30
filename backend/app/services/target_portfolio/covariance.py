"""Ledoit–Wolf covariance and a ridge when the matrix is singular or ill-conditioned.

Method: Ledoit and Wolf (2004), Journal of Multivariate Analysis,
«A well-conditioned estimator for large-dimensional covariance matrices».
Implementation: sklearn.covariance.LedoitWolf (scikit-learn 1.5).
https://scikit-learn.org/1.5/modules/covariance.html#shrunk-covariance
"""
from __future__ import annotations

import numpy as np


def ledoit_wolf(returns: np.ndarray) -> tuple[np.ndarray, str]:
    """returns shape (T, N). Raises ValueError when T < 2."""
    panel = np.asarray(returns, dtype=float)
    if panel.ndim != 2 or panel.shape[0] < 2 or panel.shape[1] < 1:
        raise ValueError("нет данных")
    if not np.isfinite(panel).all():
        raise ValueError("нет данных")
    from sklearn.covariance import LedoitWolf

    cov = np.asarray(LedoitWolf().fit(panel).covariance_, dtype=float)
    return stabilize(cov)


def stabilize(cov: np.ndarray) -> tuple[np.ndarray, str]:
    """Symmetrize. Add a ridge when an eigenvalue is ~0 or the condition number is huge."""
    matrix = np.asarray(cov, dtype=float)
    matrix = 0.5 * (matrix + matrix.T)
    if not np.isfinite(matrix).all():
        raise ValueError("нет данных")
    eig = np.linalg.eigvalsh(matrix)
    cond = float(np.linalg.cond(matrix)) if matrix.size else 0.0
    note = ""
    if float(eig.min()) < 1e-10 or cond > 1e10:
        scale = float(np.trace(matrix) / matrix.shape[0]) if matrix.shape[0] else 1.0
        eps = max(1e-8, 1e-6 * max(scale, 1e-8))
        matrix = matrix + eps * np.eye(matrix.shape[0])
        note = "ridge"
    return matrix, note


def align_returns(series: list[tuple[float, ...]]) -> np.ndarray | None:
    """Tail-align series to a common length. None when any series is shorter than 2."""
    if not series:
        return None
    length = min(len(row) for row in series)
    if length < 2:
        return None
    panel = np.column_stack([np.asarray(row[-length:], dtype=float) for row in series])
    if not np.isfinite(panel).all():
        return None
    return panel
