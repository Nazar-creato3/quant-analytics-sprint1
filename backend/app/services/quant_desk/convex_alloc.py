"""Convex projections: simplex + inverse-vol (Boyd: project onto constraints)."""
from __future__ import annotations


def inverse_vol_weights(vols: list[float]) -> list[float]:
    inv = [1.0 / v if v and v > 1e-8 else 0.0 for v in vols]
    s = sum(inv)
    if s <= 0:
        n = len(vols)
        return [1.0 / n] * n if n else []
    return [x / s for x in inv]


def project_capped_simplex(weights: list[float], *, cap: float = 0.35) -> list[float]:
    """Project onto {w >= 0, sum w = 1, w_i <= cap} by water-filling."""
    n = len(weights)
    if n == 0:
        return []
    cap = min(1.0, max(1.0 / n, cap))
    w = [max(0.0, float(x)) for x in weights]
    for _ in range(n + 2):
        s = sum(w)
        if s <= 0:
            w = [1.0 / n] * n
            s = 1.0
        w = [x / s for x in w]
        overflow = [(i, x - cap) for i, x in enumerate(w) if x > cap + 1e-12]
        if not overflow:
            return w
        for i, _ex in overflow:
            w[i] = cap
        free = [i for i, x in enumerate(w) if x < cap - 1e-12]
        leftover = 1.0 - sum(w)
        if not free or leftover <= 0:
            return [x / sum(w) for x in w]
        add = leftover / len(free)
        for i in free:
            w[i] += add
    s = sum(w) or 1.0
    return [x / s for x in w]
