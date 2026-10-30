"""Regime gate: 3-state Gaussian HMM (Baum–Welch) + hard thresholds.

States are identified by the mean of the observation (low = risk_on).
Thresholds on VIX / inverted curve / HY credit can still force shock.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

STATE_ON = 0
STATE_MIX = 1
STATE_OFF = 2
N_STATES = 3


@dataclass(frozen=True, slots=True)
class HmmFit:
    last_state: int
    posterior: tuple[float, ...]
    means: tuple[float, ...]
    n_obs: int
    n_iter: int


@dataclass(frozen=True, slots=True)
class RegimeGate:
    label: str  # risk_on | mixed | risk_off | shock
    alpha_on: bool
    size_mult: float
    hmm_state: int
    posterior: tuple[float, ...]
    breadth: float
    vix: float | None
    curve: float | None
    credit: float | None
    macro_veto: bool
    method: str


def _z(series: Sequence[float]) -> float:
    arr = np.asarray([float(x) for x in series if x is not None], dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 4:
        return 0.0
    sd = float(arr.std())
    if sd <= 1e-12:
        return 0.0
    return float((arr[-1] - float(arr.mean())) / sd)


def _finite(series: Sequence[float] | None) -> np.ndarray:
    if not series:
        return np.asarray([], dtype=float)
    arr = np.asarray([float(v) for v in series], dtype=float)
    return arr[np.isfinite(arr)]


def composite_observation(
    *,
    vix_history: Sequence[float] | None = None,
    breadth_history: Sequence[float] | None = None,
    curve_history: Sequence[float] | None = None,
    credit_history: Sequence[float] | None = None,
    vix: float | None = None,
    breadth: float | None = None,
    curve: float | None = None,
    credit: float | None = None,
) -> np.ndarray:
    """One risk factor: z(VIX) + z(-breadth) + z(-curve) + z(credit). Higher = worse."""
    series: list[np.ndarray] = []
    weights: list[float] = []

    def _pad(hist: Sequence[float] | None, last: float | None) -> np.ndarray:
        h = list(hist or [])
        if last is not None:
            h = h + [float(last)]
        return _finite(h)

    v = _pad(vix_history, vix)
    b = _pad(breadth_history, breadth)
    c = _pad(curve_history, curve)
    d = _pad(credit_history, credit)
    n = 0
    for arr in (v, b, c, d):
        if arr.size:
            n = max(n, int(arr.size))
    if n < 4:
        return np.asarray([], dtype=float)

    def _align(arr: np.ndarray) -> np.ndarray:
        if arr.size == 0:
            return np.zeros(n)
        if arr.size >= n:
            return arr[-n:]
        out = np.full(n, float(arr[0]))
        out[-arr.size :] = arr
        return out

    def _stdz(arr: np.ndarray) -> np.ndarray:
        sd = float(arr.std())
        if sd <= 1e-12:
            return np.zeros_like(arr)
        return (arr - float(arr.mean())) / sd

    if v.size:
        series.append(_stdz(_align(v)))
        weights.append(1.0)
    if b.size:
        series.append(-_stdz(_align(b)))
        weights.append(0.8)
    if c.size:
        series.append(-_stdz(_align(c)))
        weights.append(0.6)
    if d.size:
        series.append(_stdz(_align(d)))
        weights.append(0.8)
    if not series:
        return np.asarray([], dtype=float)
    w = np.asarray(weights, dtype=float)
    w = w / w.sum()
    stacked = np.column_stack(series)
    return stacked @ w


def gaussian_hmm(
    obs: Sequence[float],
    *,
    n_states: int = N_STATES,
    n_iter: int = 16,
) -> HmmFit:
    """Scaled forward–backward EM for a 1-d Gaussian HMM."""
    x = np.asarray([float(v) for v in obs], dtype=float)
    x = x[np.isfinite(x)]
    k = int(n_states)
    if x.size < k * 6:
        return HmmFit(0, tuple([1.0 / k] * k), tuple([0.0] * k), int(x.size), 0)

    qs = np.quantile(x, np.linspace(0.15, 0.85, k))
    means = qs.astype(float)
    vars_ = np.full(k, max(float(x.var()), 1e-4))
    trans = np.full((k, k), 0.08 / max(k - 1, 1))
    np.fill_diagonal(trans, 0.84)
    trans /= trans.sum(axis=1, keepdims=True)
    start = np.full(k, 1.0 / k)

    def _emit() -> np.ndarray:
        logp = -0.5 * ((x[:, None] - means) ** 2) / (vars_ + 1e-12)
        logp -= 0.5 * np.log(2.0 * np.pi * (vars_ + 1e-12))
        m = logp.max(axis=1, keepdims=True)
        like = np.exp(logp - m)
        like /= like.sum(axis=1, keepdims=True) + 1e-12
        return like

    gamma = np.zeros((x.size, k))
    for _ in range(n_iter):
        like = _emit()
        alpha = np.zeros((x.size, k))
        scale = np.zeros(x.size)
        alpha[0] = start * like[0]
        scale[0] = alpha[0].sum() + 1e-12
        alpha[0] /= scale[0]
        for t in range(1, x.size):
            alpha[t] = like[t] * (alpha[t - 1] @ trans)
            scale[t] = alpha[t].sum() + 1e-12
            alpha[t] /= scale[t]
        beta = np.ones((x.size, k))
        for t in range(x.size - 2, -1, -1):
            beta[t] = (trans @ (like[t + 1] * beta[t + 1]))
            beta[t] /= beta[t].sum() + 1e-12
        gamma = alpha * beta
        gamma /= gamma.sum(axis=1, keepdims=True) + 1e-12
        xi = np.zeros((k, k))
        for t in range(x.size - 1):
            outer = np.outer(alpha[t], like[t + 1] * beta[t + 1]) * trans
            s = outer.sum() + 1e-12
            xi += outer / s
        w = gamma.sum(axis=0) + 1e-12
        means = (gamma.T @ x) / w
        vars_ = np.array(
            [float((gamma[:, s] * (x - means[s]) ** 2).sum()) / w[s] + 1e-5 for s in range(k)]
        )
        trans = xi / (xi.sum(axis=1, keepdims=True) + 1e-12)
        start = gamma[0] / (gamma[0].sum() + 1e-12)

    last = int(np.argmax(gamma[-1]))
    order = np.argsort(means)  # low composite = risk_on
    remap = {int(order[i]): i for i in range(k)}
    remapped = int(remap.get(last, last))
    post = [0.0] * k
    for s in range(k):
        post[remap.get(s, s)] = float(gamma[-1, s])
    ordered_means = tuple(float(means[int(s)]) for s in order)
    return HmmFit(
        last_state=remapped,
        posterior=tuple(post),
        means=ordered_means,
        n_obs=int(x.size),
        n_iter=n_iter,
    )


def two_state_hmm(obs: Sequence[float], *, n_iter: int = 8) -> int:
    """Compat: 0 = calm, 1 = stress. Uses the 3-state fit (off or mix+off)."""
    fit = gaussian_hmm(obs, n_states=3, n_iter=n_iter)
    return 1 if fit.last_state >= STATE_MIX and fit.posterior[STATE_OFF] + fit.posterior[STATE_MIX] >= 0.55 else 0


def detect_regime(
    *,
    breadth: float,
    vix: float | None = None,
    curve: float | None = None,
    credit: float | None = None,
    vix_history: Sequence[float] | None = None,
    breadth_history: Sequence[float] | None = None,
    curve_history: Sequence[float] | None = None,
    credit_history: Sequence[float] | None = None,
) -> RegimeGate:
    obs = composite_observation(
        vix_history=vix_history,
        breadth_history=breadth_history,
        curve_history=curve_history,
        credit_history=credit_history,
        vix=vix,
        breadth=breadth,
        curve=curve,
        credit=credit,
    )
    fit = gaussian_hmm(obs) if obs.size >= 18 else HmmFit(0, (1.0, 0.0, 0.0), (0.0, 0.0, 0.0), int(obs.size), 0)

    vix_z = _z(list(vix_history or []) + ([float(vix)] if vix is not None else []))
    inverted = curve is not None and float(curve) < 0.0
    credit_stress = credit is not None and float(credit) >= 1.5
    vix_shock = (vix is not None and float(vix) >= 32.0) or vix_z >= 2.0
    weak_breadth = float(breadth) <= -0.25
    macro_veto = bool(vix_shock and (inverted or credit_stress))

    if macro_veto or (vix_shock and fit.last_state == STATE_OFF):
        label, alpha_on, size = "shock", False, 0.0
    elif fit.last_state == STATE_OFF or (weak_breadth and (inverted or credit_stress)):
        label, alpha_on, size = "risk_off", False, 0.0
    elif fit.last_state == STATE_MIX or weak_breadth or inverted or credit_stress:
        p_off = fit.posterior[STATE_OFF] if len(fit.posterior) > STATE_OFF else 0.0
        label, alpha_on, size = "mixed", True, max(0.25, 0.7 - 0.5 * p_off)
    else:
        label, alpha_on, size = "risk_on", True, 1.0

    if macro_veto:
        alpha_on, size, label = False, 0.0, "shock"

    return RegimeGate(
        label=label,
        alpha_on=alpha_on,
        size_mult=float(size),
        hmm_state=fit.last_state,
        posterior=fit.posterior,
        breadth=float(breadth),
        vix=None if vix is None else float(vix),
        curve=None if curve is None else float(curve),
        credit=None if credit is None else float(credit),
        macro_veto=macro_veto,
        method="threshold+hmm3_baumwelch",
    )
