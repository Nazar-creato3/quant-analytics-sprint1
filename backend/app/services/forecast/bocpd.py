"""Bayesian Online Changepoint Detection (BOCPD) parallel to HMM regime engine."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class BocpdRegimeResult:
    changepoint_probability: float
    run_length_mode: int
    regime_uncertain: bool
    agrees_with_hmm: bool | None
    hmm_regime: str | None
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "changepoint_probability": self.changepoint_probability,
            "run_length_mode": self.run_length_mode,
            "regime_uncertain": self.regime_uncertain,
            "agrees_with_hmm": self.agrees_with_hmm,
            "hmm_regime": self.hmm_regime,
            "note": self.note,
        }


def _returns(prices: Sequence[float]) -> np.ndarray:
    arr = np.asarray(prices, dtype=float)
    if len(arr) < 3:
        return np.array([])
    return np.diff(np.log(np.maximum(arr, 1e-9)))


def bocpd_changepoint_probability(
    prices: Sequence[float],
    *,
    hazard: float = 1.0 / 50.0,
) -> BocpdRegimeResult:
    """Lightweight Gaussian BOCPD; returns P(changepoint at t) and run-length mode.

    Implements Adams & MacKay (2007) style online message passing with a
    normal-gamma-like constant-variance approximation suitable for daily returns.
    """
    rets = _returns(prices)
    if len(rets) < 20:
        return BocpdRegimeResult(0.0, len(rets), True, None, None, "insufficient_history")

    # Online sufficient stats for run length posterior.
    # R[t] ≈ P(r_t | x_1:t); we keep a truncated distribution.
    max_run = min(200, len(rets))
    R = np.zeros(max_run + 1)
    R[0] = 1.0
    mu0, kappa0, alpha0, beta0 = 0.0, 1.0, 1.0, 0.0001
    # Per-run-length params
    mu = np.full(max_run + 1, mu0)
    kappa = np.full(max_run + 1, kappa0)
    alpha = np.full(max_run + 1, alpha0)
    beta = np.full(max_run + 1, beta0)
    last_cp_prob = 0.0

    for x in rets[-(max_run):]:
        # Predictive probability under each run length (Student-t approx).
        pred = np.zeros(max_run + 1)
        for r in range(max_run + 1):
            if R[r] <= 0:
                continue
            var = beta[r] * (kappa[r] + 1) / (alpha[r] * kappa[r])
            var = max(var, 1e-12)
            # Gaussian predictive density
            pred[r] = np.exp(-0.5 * (x - mu[r]) ** 2 / var) / np.sqrt(2 * np.pi * var)

        growth = R * pred * (1.0 - hazard)
        cp_prob = float(np.sum(R * pred * hazard))
        new_R = np.zeros_like(R)
        new_R[1:] = growth[:-1]
        new_R[0] = cp_prob
        s = new_R.sum()
        if s > 0:
            new_R /= s
        R = new_R
        last_cp_prob = cp_prob / max(s, 1e-12) if s > 0 else cp_prob

        # Update params for surviving runs (shift)
        new_mu = np.full_like(mu, mu0)
        new_kappa = np.full_like(kappa, kappa0)
        new_alpha = np.full_like(alpha, alpha0)
        new_beta = np.full_like(beta, beta0)
        for r in range(max_run):
            if R[r + 1] <= 0 and r + 1 > 0:
                continue
            k = kappa[r]
            m = mu[r]
            a = alpha[r]
            b = beta[r]
            new_kappa[r + 1] = k + 1
            new_mu[r + 1] = (k * m + x) / (k + 1)
            new_alpha[r + 1] = a + 0.5
            new_beta[r + 1] = b + 0.5 * k * (x - m) ** 2 / (k + 1)
        mu, kappa, alpha, beta = new_mu, new_kappa, new_alpha, new_beta

    run_mode = int(np.argmax(R))
    regime_uncertain = last_cp_prob >= 0.25 or run_mode <= 3
    return BocpdRegimeResult(
        changepoint_probability=float(min(1.0, max(0.0, last_cp_prob))),
        run_length_mode=run_mode,
        regime_uncertain=regime_uncertain,
        agrees_with_hmm=None,
        hmm_regime=None,
        note="bocpd_gaussian",
    )


def combine_bocpd_with_hmm(
    prices: Sequence[float],
    hmm_regime: str | None,
    *,
    hmm_confidence: float = 0.5,
) -> BocpdRegimeResult:
    """Agree → higher confidence; disagree / fresh changepoint → regime-uncertain."""
    base = bocpd_changepoint_probability(prices)
    if hmm_regime is None:
        return BocpdRegimeResult(
            base.changepoint_probability,
            base.run_length_mode,
            base.regime_uncertain,
            None,
            None,
            base.note,
        )

    # Heuristic agreement: long run-length + high HMM confidence ⇒ agree.
    agrees = (not base.regime_uncertain) and hmm_confidence >= 0.55 and base.run_length_mode >= 10
    disagree = base.changepoint_probability >= 0.35 and hmm_confidence >= 0.55
    uncertain = base.regime_uncertain or disagree or (not agrees and hmm_confidence < 0.45)
    return BocpdRegimeResult(
        changepoint_probability=base.changepoint_probability,
        run_length_mode=base.run_length_mode,
        regime_uncertain=uncertain,
        agrees_with_hmm=agrees and not disagree,
        hmm_regime=hmm_regime,
        note="bocpd+hmm",
    )
