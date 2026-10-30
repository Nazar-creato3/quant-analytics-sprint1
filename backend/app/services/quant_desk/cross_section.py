"""Qlib-style cross-sectional z-score (rank residual, not raw return)."""
from __future__ import annotations


def zscore(values: list[float]) -> list[float]:
    n = len(values)
    if n == 0:
        return []
    mu = sum(values) / n
    var = sum((v - mu) ** 2 for v in values) / n
    sd = var**0.5
    if sd <= 1e-12:
        return [0.0] * n
    return [(v - mu) / sd for v in values]


def neutralize(
    values: list[float],
    *,
    sectors: list[str] | None = None,
    size: list[float] | None = None,
    beta: list[float] | None = None,
) -> list[float]:
    """Sector / size / beta residual z-score (Qlib-style, no Qlib)."""
    from app.services.alpha.neutralization import neutralize_cs

    return list(neutralize_cs(values, sectors=sectors, size=size, beta=beta).z)


def rank_01(values: list[float]) -> list[float]:
    n = len(values)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: values[i])
    out = [0.0] * n
    if n == 1:
        return [0.5]
    for r, i in enumerate(order):
        out[i] = r / (n - 1)
    return out
