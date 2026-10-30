"""Glasserman: antithetic variates for a 1-D Gaussian path mean."""
from __future__ import annotations

import math
import random


def antithetic_mean(
    n_pairs: int,
    *,
    mu: float,
    sigma: float,
    rng: random.Random | None = None,
) -> float:
    if n_pairs <= 0 or sigma < 0:
        return mu
    r = rng or random.Random(7)
    acc = 0.0
    for _ in range(n_pairs):
        u = r.random()
        # Box–Muller one normal
        z = math.sqrt(-2.0 * math.log(max(u, 1e-12))) * math.cos(2 * math.pi * r.random())
        acc += mu + sigma * z
        acc += mu - sigma * z
    return acc / (2 * n_pairs)
