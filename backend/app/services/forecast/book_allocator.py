"""Book weights: conviction tilt, optional CVaR-lite from history. Never lever up."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np


def _cap_renorm(weights: list[float], cap: float) -> list[float]:
    w = [max(0.0, float(x)) for x in weights]
    for _ in range(8):
        total = sum(w)
        if total <= 1e-12:
            n = len(w)
            return [1.0 / n] * n if n else []
        w = [x / total for x in w]
        overflow = False
        leftover = 0.0
        free: list[int] = []
        for i, x in enumerate(w):
            if x > cap + 1e-12:
                leftover += x - cap
                w[i] = cap
                overflow = True
            else:
                free.append(i)
        if not overflow or not free:
            break
        add = leftover / len(free)
        for i in free:
            w[i] += add
    total = sum(w)
    return [x / total for x in w] if total > 1e-12 else w


def conviction_raw(rows: Sequence[Mapping[str, Any]]) -> list[float]:
    raw: list[float] = []
    for r in rows:
        score = max(
            0,
            int(r.get("score_21") or r.get("score_5") or r.get("score_20") or 0),
        )
        p = r.get("p_beat_21", r.get("p_beat_5", r.get("p_beat_20")))
        try:
            p_f = float(p) if p is not None else 0.5
        except (TypeError, ValueError):
            p_f = 0.5
        edge = max(p_f - 0.5, 0.0)
        raw.append(max(edge * (score / 10.0), 1e-6))
    return raw


def cvar_lite_raw(
    names: Sequence[str],
    hist: Mapping[str, Sequence[float]],
    *,
    alpha: float = 0.95,
) -> list[float] | None:
    """Inverse left-tail: worse α-quantile → smaller weight. Needs ≥20 days each."""
    cols: list[np.ndarray] = []
    for name in names:
        series = [float(x) for x in (hist.get(name) or []) if x is not None]
        if len(series) < 20:
            return None
        cols.append(np.asarray(series, dtype=float))
    tails: list[float] = []
    for col in cols:
        q = float(np.quantile(col, 1.0 - alpha))
        tails.append(max(-q, 1e-6))
    inv = [1.0 / t for t in tails]
    return inv


def mean_cvar_weights(
    hist: Mapping[str, Sequence[float]],
    names: Sequence[str],
    *,
    cap: float,
    alpha: float = 0.95,
) -> list[float] | None:
    """Long-only mean-CVaR tilt. Returns None if the panel is too short."""
    cols: list[np.ndarray] = []
    length = None
    for name in names:
        series = [float(x) for x in (hist.get(name) or []) if x is not None]
        if len(series) < 20:
            return None
        if length is None:
            length = len(series)
        cols.append(np.asarray(series[-min(length, len(series)) :], dtype=float))
    T = min(c.size for c in cols)
    if T < 20:
        return None
    R = np.column_stack([c[-T:] for c in cols])
    n = R.shape[1]
    effective = cap if n * cap >= 1.0 + 1e-9 else 1.0
    w = np.ones(n) / n
    for _ in range(20):
        port = R @ w
        q = float(np.quantile(port, 1.0 - alpha))
        tail = port <= q + 1e-12
        if not np.any(tail):
            break
        grad = 0.7 * R[tail].mean(axis=0) - 0.3 * R.mean(axis=0)
        w = np.maximum(w - 0.12 * grad, 0.0)
        if float(w.sum()) <= 1e-12:
            w = np.ones(n) / n
            break
        w = np.asarray(_cap_renorm(w.tolist(), effective), dtype=float)
    return w.tolist()


def allocate_book_weights(
    rows: Sequence[Mapping[str, Any]],
    *,
    hist_returns: Mapping[str, Sequence[float]] | None = None,
    cap: float = 0.25,
) -> tuple[list[float], str]:
    n = len(rows)
    if n == 0:
        return [], "empty"
    capped = n * float(cap) >= 1.0 + 1e-9
    effective_cap = float(cap) if capped else 1.0
    names = [str(r.get("symbol") or "").upper() for r in rows]
    suffix = "_cap_25" if capped else ""
    if hist_returns:
        cvar = mean_cvar_weights(hist_returns, names, cap=effective_cap)
        if cvar is not None:
            conv = conviction_raw(rows)
            mixed = [a * b for a, b in zip(cvar, conv)]
            return _cap_renorm(mixed, effective_cap), f"mean_cvar_x_conviction{suffix}"
        tail = cvar_lite_raw(names, hist_returns)
        if tail is not None:
            conv = conviction_raw(rows)
            mixed = [t * c for t, c in zip(tail, conv)]
            return _cap_renorm(mixed, effective_cap), f"cvar_lite_x_conviction{suffix}"
    return _cap_renorm(conviction_raw(rows), effective_cap), f"conviction_p_beat{suffix}"
