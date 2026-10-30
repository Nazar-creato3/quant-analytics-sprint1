"""User confidence-threshold filtering for maneuver proposals."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_SUGGESTED_THRESHOLD = 0.65
_MAX_SUGGESTED_THRESHOLD = 0.70
_MIN_SUGGESTED_THRESHOLD = 0.45
# Only treat empty books as "threshold too high" at extreme operator settings.
EXTREME_CONFIDENCE_THRESHOLD = 0.95


@dataclass
class ConfidenceFilterResult:
    """Outcome of applying the operator's confidence threshold to a candidate set."""

    threshold: float
    max_available_confidence: float | None
    tradeable_count: int
    threshold_too_high: bool
    suggested_threshold: float | None
    message: str | None
    above_threshold_count: int = 0
    backfill_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "threshold": self.threshold,
            "max_available_confidence": self.max_available_confidence,
            "tradeable_count": self.tradeable_count,
            "above_threshold_count": self.above_threshold_count,
            "backfill_count": self.backfill_count,
            "threshold_too_high": self.threshold_too_high,
            "suggested_threshold": self.suggested_threshold,
            "message": self.message,
        }


def max_directional_confidence(candidates: list[Any]) -> float | None:
    """Highest ML confidence among non-neutral candidates."""
    confidences = [
        float(c.prediction.confidence)
        for c in candidates
        if getattr(c.prediction, "direction", "neutral") != "neutral"
    ]
    if not confidences:
        return None
    return max(confidences)


def suggest_confidence_threshold(max_confidence: float) -> float:
    """Pick a practical threshold at or below the best available signal (45–70%)."""
    pct = int(max_confidence * 100 // 5) * 5
    suggested = max(_MIN_SUGGESTED_THRESHOLD, pct / 100.0)
    return min(suggested, _MAX_SUGGESTED_THRESHOLD)


def build_confidence_empty_message(suggested_threshold: float) -> str:
    suggested_pct = int(round(suggested_threshold * 100))
    return (
        "Сделок, подходящих под такой порог уверенности, нет. "
        f"Порог нереалистично высокий — установите порог около {suggested_pct}%, "
        "чтобы увидеть возможные сделки."
    )


def build_confidence_filter_result(
    threshold: float,
    *,
    max_available_confidence: float | None,
    tradeable_count: int,
    above_threshold_count: int | None = None,
    backfill_count: int = 0,
) -> ConfidenceFilterResult:
    """Build structured empty-state metadata when nothing passes the threshold."""
    above = tradeable_count if above_threshold_count is None else above_threshold_count
    threshold_too_high = (
        tradeable_count == 0
        and threshold >= EXTREME_CONFIDENCE_THRESHOLD - 1e-9
        and max_available_confidence is not None
        and threshold > max_available_confidence + 1e-9
    )
    suggested: float | None = None
    message: str | None = None
    if tradeable_count == 0 and max_available_confidence is not None:
        if threshold > max_available_confidence + 1e-9:
            suggested = suggest_confidence_threshold(max_available_confidence)
            message = build_confidence_empty_message(suggested)
            threshold_too_high = threshold >= EXTREME_CONFIDENCE_THRESHOLD - 1e-9
    elif above == 0 and backfill_count > 0 and tradeable_count > 0:
        pct = int(round(threshold * 100))
        message = (
            f"Ни один сигнал не достиг порога {pct}%; в отчёте {backfill_count} "
            "лучших доступных ниже порога — проверьте catalyst перед одобрением."
        )
    return ConfidenceFilterResult(
        threshold=threshold,
        max_available_confidence=max_available_confidence,
        tradeable_count=tradeable_count,
        above_threshold_count=above,
        backfill_count=backfill_count,
        threshold_too_high=threshold_too_high,
        suggested_threshold=suggested,
        message=message,
    )


def passes_confidence_threshold(confidence: float, threshold: float) -> bool:
    return confidence >= threshold - 1e-9
