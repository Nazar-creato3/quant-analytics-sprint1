"""Qlib-style cross-sectional neutralization without a Qlib vendor.

Each cross-section: residualize raw values on sector dummies + size + beta.
Returns z-scored residuals so ranking is style-neutral, not raw momentum.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from app.services.quant_desk.cross_section import zscore


@dataclass(frozen=True, slots=True)
class NeutralizedPanel:
    raw: tuple[float, ...]
    residual: tuple[float, ...]
    z: tuple[float, ...]
    factors: tuple[str, ...]
    rank_deficient: bool


def _sector_dummies(sectors: Sequence[str]) -> tuple[np.ndarray, tuple[str, ...]]:
    names = sorted({str(s or "UNK") for s in sectors})
    # Drop last dummy to avoid dummy trap with intercept.
    keep = names[:-1] if len(names) > 1 else names
    mat = np.zeros((len(sectors), len(keep)), dtype=float)
    index = {n: i for i, n in enumerate(keep)}
    for r, s in enumerate(sectors):
        j = index.get(str(s or "UNK"))
        if j is not None:
            mat[r, j] = 1.0
    return mat, tuple(keep)


def neutralize_cs(
    values: Sequence[float],
    *,
    sectors: Sequence[str] | None = None,
    size: Sequence[float] | None = None,
    beta: Sequence[float] | None = None,
) -> NeutralizedPanel:
    """OLS residual vs sector / log-size / beta. Falls back to CS z-score if rank fails."""
    y = np.asarray([float(v) for v in values], dtype=float)
    n = int(y.size)
    if n == 0:
        return NeutralizedPanel((), (), (), (), False)
    if n == 1:
        return NeutralizedPanel((float(y[0]),), (0.0,), (0.0,), ("intercept",), True)

    cols: list[np.ndarray] = [np.ones(n)]
    names: list[str] = ["intercept"]
    if sectors is not None and len(sectors) == n:
        dum, dum_names = _sector_dummies(sectors)
        if dum.size:
            cols.append(dum)
            names.extend(f"sector_{k}" for k in dum_names)
    if size is not None and len(size) == n:
        log_size = np.log(np.maximum(np.asarray(size, dtype=float), 1e-12))
        cols.append(log_size.reshape(-1, 1) if log_size.ndim == 1 else log_size)
        names.append("size")
    if beta is not None and len(beta) == n:
        b = np.asarray(beta, dtype=float)
        cols.append(b.reshape(-1, 1))
        names.append("beta")

    pieces = []
    for c in cols:
        pieces.append(c.reshape(n, -1))
    X = np.hstack(pieces)
    rank_deficient = False
    try:
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        fitted = X @ coef
        resid = y - fitted
        if not np.all(np.isfinite(resid)):
            raise np.linalg.LinAlgError("non-finite residual")
        # Degenerate: residual ≈ 0 everywhere (X spans y).
        if float(np.std(resid)) < 1e-15:
            rank_deficient = True
            resid = y - float(np.mean(y))
    except (np.linalg.LinAlgError, ValueError):
        rank_deficient = True
        resid = y - float(np.mean(y))

    z = zscore(resid.tolist())
    return NeutralizedPanel(
        raw=tuple(float(v) for v in y),
        residual=tuple(float(v) for v in resid),
        z=tuple(float(v) for v in z),
        factors=tuple(names),
        rank_deficient=rank_deficient,
    )


def neutralize_matrix(
    panel: Sequence[Sequence[float]],
    *,
    sectors: Sequence[str] | None = None,
    size: Sequence[float] | None = None,
    beta: Sequence[float] | None = None,
) -> list[list[float]]:
    """Row-wise (one date) neutralization of a names×features slice."""
    if not panel:
        return []
    cols = list(zip(*panel))
    out_cols: list[tuple[float, ...]] = []
    for col in cols:
        neu = neutralize_cs(col, sectors=sectors, size=size, beta=beta)
        out_cols.append(neu.z)
    rows = list(zip(*out_cols))
    return [list(r) for r in rows]
