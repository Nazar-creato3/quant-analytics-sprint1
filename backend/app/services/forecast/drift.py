"""PSI on daily returns. No vendor. High PSI → allow retrain; quiet tape → keep last-good."""

from __future__ import annotations

from typing import Sequence

import numpy as np


def population_stability_index(
    recent: Sequence[float],
    baseline: Sequence[float],
    *,
    n_bins: int = 8,
) -> float:
    a = np.asarray([float(x) for x in recent if np.isfinite(x)], dtype=float)
    b = np.asarray([float(x) for x in baseline if np.isfinite(x)], dtype=float)
    if a.size < 20 or b.size < 20:
        return 0.0
    edges = np.quantile(b, np.linspace(0.0, 1.0, n_bins + 1))
    edges[0] -= 1e-9
    edges[-1] += 1e-9
    if np.any(np.diff(edges) <= 0):
        return 0.0
    h_a, _ = np.histogram(a, bins=edges)
    h_b, _ = np.histogram(b, bins=edges)
    p = np.clip(h_a / max(h_a.sum(), 1), 1e-4, 1.0)
    q = np.clip(h_b / max(h_b.sum(), 1), 1e-4, 1.0)
    return float(np.sum((p - q) * np.log(p / q)))


def returns_psi(closes: Sequence[float], *, split: int = 40) -> float:
    px = [float(x) for x in closes if x and float(x) > 0]
    if len(px) < split * 2 + 2:
        return 1.0  # not enough history → do not skip retrain
    rets = [px[i] / px[i - 1] - 1.0 for i in range(1, len(px))]
    return population_stability_index(rets[-split:], rets[-2 * split : -split])


def should_skip_retrain(closes: Sequence[float], *, artifact_exists: bool) -> bool:
    """Skip nightly fit when the tape did not shift and a last-good file exists."""
    if not artifact_exists:
        return False
    return returns_psi(closes) < 0.10
