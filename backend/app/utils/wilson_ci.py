"""Wilson score interval for binomial proportion (accuracy) estimates."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WilsonInterval:
    """95% Wilson score confidence interval for a binomial proportion."""

    successes: int
    trials: int
    proportion: float
    ci_low: float
    ci_high: float
    confidence: float = 0.95

    @property
    def sample_size(self) -> int:
        return self.trials


def wilson_ci(
    successes: int,
    trials: int,
    *,
    confidence: float = 0.95,
) -> WilsonInterval | None:
    """Compute Wilson score interval; returns None when trials == 0."""
    if trials <= 0:
        return None
    if successes < 0 or successes > trials:
        raise ValueError("successes must be between 0 and trials inclusive")

    z = _z_for_confidence(confidence)
    n = float(trials)
    p_hat = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p_hat + z2 / (2.0 * n)) / denom
    margin = (z / denom) * math.sqrt((p_hat * (1.0 - p_hat) / n) + (z2 / (4.0 * n * n)))
    low = max(0.0, center - margin)
    high = min(1.0, center + margin)
    return WilsonInterval(
        successes=successes,
        trials=trials,
        proportion=p_hat,
        ci_low=low,
        ci_high=high,
        confidence=confidence,
    )


def wilson_ci_from_rate(
    accuracy: float | None,
    sample_size: int,
    *,
    confidence: float = 0.95,
) -> WilsonInterval | None:
    """Build Wilson interval from mean accuracy and sample count."""
    if sample_size <= 0 or accuracy is None:
        return None
    successes = int(round(accuracy * sample_size))
    successes = max(0, min(sample_size, successes))
    return wilson_ci(successes, sample_size, confidence=confidence)


def format_accuracy_with_ci_ru(
    accuracy: float | None,
    *,
    ci_low: float | None = None,
    ci_high: float | None = None,
    sample_size: int | None = None,
    confidence_pct: int = 95,
) -> str:
    """Format like «46.7% (95% ДИ: 38–56%, n=142)»."""
    if accuracy is None:
        return "—"
    pct = f"{accuracy * 100:.1f}%"
    if ci_low is None or ci_high is None or sample_size is None:
        return pct
    lo = int(round(ci_low * 100))
    hi = int(round(ci_high * 100))
    return f"{pct} ({confidence_pct}% ДИ: {lo}–{hi}%, n={sample_size})"


def _z_for_confidence(confidence: float) -> float:
    if confidence >= 0.999:
        return 3.291
    if confidence >= 0.99:
        return 2.576
    if confidence >= 0.95:
        return 1.96
    if confidence >= 0.90:
        return 1.645
    raise ValueError("unsupported confidence level; use >= 0.90")
