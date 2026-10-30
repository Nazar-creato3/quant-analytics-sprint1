"""Lightweight Gaussian HMM for sequence-aware regime classification."""
from __future__ import annotations

import math
from typing import Sequence

from app.services.regime.types import ALL_REGIME_LABELS, MarketRegimeLabel, RegimeFeatureVector


def _gaussian_pdf(value: float, mean: float, std: float) -> float:
    if std <= 0.0:
        return 1.0 if math.isclose(value, mean, abs_tol=1e-9) else 1e-12
    z = (value - mean) / std
    return math.exp(-0.5 * z * z) / (std * math.sqrt(2.0 * math.pi))


def _emission_log_prob(observation: Sequence[float], means: Sequence[float], std: float) -> float:
    log_prob = 0.0
    for value, mean in zip(observation, means, strict=True):
        density = _gaussian_pdf(value, mean, std)
        log_prob += math.log(max(density, 1e-300))
    return log_prob


# Emission centers tuned for normalized feature space.
_REGIME_EMISSION_MEANS: dict[MarketRegimeLabel, tuple[float, ...]] = {
    MarketRegimeLabel.BULLISH_TREND: (0.75, 0.78, 0.95, 0.35, 0.25, 0.20, 0.30),
    MarketRegimeLabel.BEARISH_TREND: (-0.75, 0.22, 0.95, 0.35, 0.20, 0.20, 0.30),
    MarketRegimeLabel.CHOPPY_RANGE: (0.02, 0.50, 0.90, 0.25, 0.00, 0.25, 0.35),
    MarketRegimeLabel.HIGH_VOLATILITY_SHOCK: (0.05, 0.50, 2.40, 0.90, 0.45, 0.35, 0.55),
    MarketRegimeLabel.LIQUIDITY_DROUGHT: (0.00, 0.50, 1.05, 0.40, -0.25, 0.88, 0.40),
    MarketRegimeLabel.MACRO_UNCERTAINTY: (0.00, 0.50, 1.20, 0.50, 0.05, 0.35, 0.88),
}

_EMISSION_STD = 0.35
_PERSISTENCE = 0.82
_CROSS_TRANSITION = (1.0 - _PERSISTENCE) / (len(ALL_REGIME_LABELS) - 1)


def _build_transition_matrix() -> list[list[float]]:
    size = len(ALL_REGIME_LABELS)
    matrix: list[list[float]] = []
    for row in range(size):
        matrix.append(
            [
                _PERSISTENCE if column == row else _CROSS_TRANSITION
                for column in range(size)
            ]
        )
    return matrix


def _normalize(probabilities: list[float]) -> list[float]:
    total = sum(probabilities)
    if total <= 0.0:
        uniform = 1.0 / len(probabilities)
        return [uniform] * len(probabilities)
    return [value / total for value in probabilities]


def _entropy(probabilities: Sequence[float]) -> float:
    entropy = 0.0
    for probability in probabilities:
        if probability > 0.0:
            entropy -= probability * math.log(probability)
    return entropy


def classify_sequence(
    feature_sequence: Sequence[RegimeFeatureVector],
) -> tuple[dict[str, float], float]:
    """Run forward filtering and return normalized regime probabilities + confidence."""
    if not feature_sequence:
        uniform = 1.0 / len(ALL_REGIME_LABELS)
        distribution = {label.value: uniform for label in ALL_REGIME_LABELS}
        return distribution, 1.0 / len(ALL_REGIME_LABELS)

    transition = _build_transition_matrix()
    state_count = len(ALL_REGIME_LABELS)
    alpha = [1.0 / state_count] * state_count

    for feature in feature_sequence:
        observation = feature.as_list()
        emission = [
            math.exp(
                _emission_log_prob(
                    observation,
                    _REGIME_EMISSION_MEANS[label],
                    _EMISSION_STD,
                )
            )
            for label in ALL_REGIME_LABELS
        ]

        next_alpha = [0.0] * state_count
        for next_state in range(state_count):
            for prev_state in range(state_count):
                next_alpha[next_state] += (
                    alpha[prev_state] * transition[prev_state][next_state] * emission[next_state]
                )
        alpha = _normalize(next_alpha)

    distribution = {
        label.value: alpha[index]
        for index, label in enumerate(ALL_REGIME_LABELS)
    }
    dominant_probability = max(alpha)
    max_entropy = math.log(state_count)
    entropy = _entropy(alpha)
    confidence = dominant_probability * (1.0 - entropy / max_entropy)
    confidence = max(0.0, min(0.95, confidence))
    return distribution, confidence
