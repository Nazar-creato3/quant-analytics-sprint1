"""Forward-looking validation helpers for ReplayEngine prediction replay."""
from __future__ import annotations

import math
from typing import Sequence

from app.services.regime.engine import RegimeEngine
from app.services.regime.features import build_feature_vector
from app.services.regime.types import MarketRegimeLabel


def infer_actual_regime_from_forward_prices(
    forward_prices: Sequence[float],
    *,
    spread_bps: float | None = None,
    correlation_cluster: float = 0.0,
    regime_engine: RegimeEngine | None = None,
    min_prices_for_engine: int = 25,
) -> str:
    """Classify subsequent price behavior for forward-looking regime validation."""
    prices = list(forward_prices)
    if len(prices) < 2:
        return MarketRegimeLabel.CHOPPY_RANGE.value

    if len(prices) >= min_prices_for_engine:
        engine = regime_engine or RegimeEngine()
        return engine.classify_instrument(
            prices,
            spread_bps=spread_bps,
            correlation_cluster=correlation_cluster,
        ).dominant_regime

    feature = build_feature_vector(
        prices,
        spread_bps=spread_bps,
        correlation_cluster=correlation_cluster,
    )
    cumulative_return = _cumulative_return(prices)
    if feature.spread_norm > 0.5:
        return MarketRegimeLabel.LIQUIDITY_DROUGHT.value
    if correlation_cluster > 0.9:
        return MarketRegimeLabel.MACRO_UNCERTAINTY.value
    if feature.vol_ratio > 1.5 or feature.vol_level > 0.5:
        return MarketRegimeLabel.HIGH_VOLATILITY_SHOCK.value
    if cumulative_return > 0.03 or feature.trend_slope > 0.35:
        return MarketRegimeLabel.BULLISH_TREND.value
    if cumulative_return < -0.03 or feature.trend_slope < -0.35:
        return MarketRegimeLabel.BEARISH_TREND.value
    return MarketRegimeLabel.CHOPPY_RANGE.value


def _cumulative_return(prices: Sequence[float]) -> float:
    if len(prices) < 2 or prices[0] <= 0.0:
        return 0.0
    return (prices[-1] - prices[0]) / prices[0]


def build_regime_confusion_matrix(
    predicted: Sequence[str],
    actual: Sequence[str],
    *,
    labels: Sequence[str] | None = None,
) -> dict[str, dict[str, int]]:
    """Build predicted-vs-actual regime confusion matrix."""
    if len(predicted) != len(actual):
        raise ValueError("predicted and actual sequences must have equal length")

    label_set = set(labels or [])
    label_set.update(predicted)
    label_set.update(actual)
    ordered_labels = tuple(sorted(label_set))

    matrix: dict[str, dict[str, int]] = {
        predicted_label: {actual_label: 0 for actual_label in ordered_labels}
        for predicted_label in ordered_labels
    }
    for predicted_label, actual_label in zip(predicted, actual, strict=True):
        matrix[predicted_label][actual_label] += 1
    return matrix


def regime_classification_accuracy(predicted: Sequence[str], actual: Sequence[str]) -> float:
    """Fraction of points where predicted dominant regime equals actual forward regime."""
    if not predicted:
        return 0.0
    matches = sum(1 for pred, act in zip(predicted, actual, strict=True) if pred == act)
    return matches / len(predicted)


def compute_forecast_calibration(
    confidences: Sequence[float],
    regime_matches: Sequence[bool],
    *,
    bin_count: int = 5,
) -> tuple[tuple[dict[str, float | int], ...], float]:
    """Bin forecast confidence and measure regime-match accuracy per bin."""
    if len(confidences) != len(regime_matches):
        raise ValueError("confidences and regime_matches must have equal length")
    if not confidences:
        return (), 0.0

    pairs = sorted(zip(confidences, regime_matches), key=lambda item: item[0])
    size = len(pairs)
    bins: list[dict[str, float | int]] = []

    for bin_index in range(bin_count):
        start = (bin_index * size) // bin_count
        end = ((bin_index + 1) * size) // bin_count
        bucket = pairs[start:end]
        if not bucket:
            continue
        bucket_confidences = [item[0] for item in bucket]
        bucket_matches = [item[1] for item in bucket]
        bins.append(
            {
                "confidence_min": min(bucket_confidences),
                "confidence_max": max(bucket_confidences),
                "count": len(bucket),
                "accuracy": sum(1 for matched in bucket_matches if matched) / len(bucket_matches),
            }
        )

    confidence_values = [value for value, _ in pairs]
    match_values = [1.0 if matched else 0.0 for _, matched in pairs]
    correlation = _pearson_correlation(confidence_values, match_values)
    return tuple(bins), correlation


def _pearson_correlation(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) < 2 or len(left) != len(right):
        return 0.0

    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    numerator = sum(
        (left_value - mean_left) * (right_value - mean_right)
        for left_value, right_value in zip(left, right, strict=True)
    )
    denom_left = math.sqrt(sum((value - mean_left) ** 2 for value in left))
    denom_right = math.sqrt(sum((value - mean_right) ** 2 for value in right))
    if denom_left <= 1e-12 or denom_right <= 1e-12:
        return 0.0
    return max(-1.0, min(1.0, numerator / (denom_left * denom_right)))
