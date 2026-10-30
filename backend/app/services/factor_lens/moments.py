"""Covariance used by the factor lens. skfolio 0.6.0 is the product pin (BSD-3).

skfolio 0.6.0 cannot be imported on CPython 3.13 + current cvxpy: package
``__init__`` evaluates ``cp.Expression | cp.trace`` and raises TypeError.
The pin stays; Ledoit–Wolf at runtime is sklearn until a skfolio line that
imports on this stack is allowed (would need sklearn>=1.6, ADR).
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Sequence

import numpy as np
from sklearn.covariance import LedoitWolf

try:
    SKFOLIO_VERSION = version("skfolio")
except PackageNotFoundError:
    SKFOLIO_VERSION = "unavailable"


def ledoit_wolf_covariance(returns: Sequence[Sequence[float]]) -> np.ndarray:
    matrix = np.asarray(returns, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] < 2 or matrix.shape[1] < 1:
        n = 1 if matrix.ndim < 2 else max(matrix.shape[1], 1)
        return np.eye(n) * 1e-8
    cov = np.asarray(LedoitWolf().fit(matrix).covariance_, dtype=float)
    return 0.5 * (cov + cov.T)
