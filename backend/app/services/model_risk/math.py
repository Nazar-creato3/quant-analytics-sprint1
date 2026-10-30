"""Leakage, baselines, Brier, PSI, conformal coverage (Prompt 11B)."""
from __future__ import annotations

import math
from typing import Sequence

from app.services.quant_math.core import correlation


def detect_lookahead(feature: Sequence[float], realized: Sequence[float], *, threshold: float = 0.45) -> bool:
    """True if feature at t is aligned with return at t+1 (future leak)."""
    n = min(len(feature), len(realized)) - 1
    if n < 8:
        return False
    leaked = [float(feature[i]) for i in range(n)]
    future = [float(realized[i + 1]) for i in range(n)]
    return abs(correlation(leaked, future)) >= threshold


def purged_walk_forward(returns: Sequence[float], *, embargo: int = 1) -> list[int]:
    """Predict sign of next return from past mean; skip embargo after each step."""
    values = [float(x) for x in returns]
    preds: list[int] = []
    i = 5
    while i + 1 + embargo < len(values):
        past = values[:i]
        mean = sum(past) / len(past)
        preds.append(1 if mean > 0 else (-1 if mean < 0 else 0))
        i += 1 + embargo
    return preds


def naive_persist(returns: Sequence[float]) -> list[int]:
    values = [float(x) for x in returns]
    out = [0]
    for prev in values[:-1]:
        out.append(1 if prev > 0 else (-1 if prev < 0 else 0))
    return out


def naive_constant(n: int, direction: int = 1) -> list[int]:
    return [direction] * n


def brier(probs: Sequence[float], outcomes: Sequence[int]) -> float:
    pairs = list(zip(probs, outcomes))
    if not pairs:
        return 0.0
    return sum((float(p) - (1.0 if y > 0 else 0.0)) ** 2 for p, y in pairs) / len(pairs)


def binomial_p_beats_half(hits: int, n: int) -> float:
    """Two-sided binomial p-value vs 0.5 (normal approximation)."""
    if n <= 0:
        return 1.0
    phat = hits / n
    se = math.sqrt(0.25 / n)
    if se == 0:
        return 1.0
    z = abs(phat - 0.5) / se
    return math.erfc(z / math.sqrt(2.0))


def diebold_mariano(err_a: Sequence[float], err_b: Sequence[float]) -> float:
    """DM statistic (loss differential a-b); positive ⇒ a worse than b."""
    d = [float(a) - float(b) for a, b in zip(err_a, err_b)]
    if len(d) < 3:
        return 0.0
    mean = sum(d) / len(d)
    var = sum((x - mean) ** 2 for x in d) / (len(d) - 1)
    if var <= 0:
        return 0.0
    return mean / math.sqrt(var / len(d))


def psi(expected: Sequence[float], actual: Sequence[float], bins: int = 10) -> float:
    if not expected or not actual:
        return 0.0
    lo = min(min(expected), min(actual))
    hi = max(max(expected), max(actual))
    if hi <= lo:
        return 0.0
    width = (hi - lo) / bins
    def _hist(xs: Sequence[float]) -> list[float]:
        counts = [0.0] * bins
        for x in xs:
            idx = min(bins - 1, int((float(x) - lo) / width))
            counts[idx] += 1
        n = max(1.0, sum(counts))
        return [max(c / n, 1e-6) for c in counts]
    e, a = _hist(expected), _hist(actual)
    return sum((ai - ei) * math.log(ai / ei) for ai, ei in zip(a, e))


def conformal_interval(residuals: Sequence[float], point: float, alpha: float = 0.1) -> tuple[float, float]:
    vals = sorted(abs(float(r)) for r in residuals)
    if not vals:
        return point, point
    rank = min(len(vals) - 1, max(0, math.ceil((1.0 - alpha) * len(vals)) - 1))
    q = vals[rank]
    return point - q, point + q


def coverage(realized: Sequence[float], lows: Sequence[float], highs: Sequence[float]) -> float:
    n = min(len(realized), len(lows), len(highs))
    if n == 0:
        return 0.0
    hits = sum(1 for i in range(n) if lows[i] <= realized[i] <= highs[i])
    return hits / n
