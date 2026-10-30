"""Public track record response types — aggregate only, no client identifiers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RegimeAccuracyRow:
    regime: str
    accuracy: float
    sample_size: int
    confidence_note: str


@dataclass(frozen=True, slots=True)
class LevelAccuracyRow:
    level: str
    accuracy: float
    total_points: int
    notes: str = ""


@dataclass(frozen=True, slots=True)
class PublicTrackRecordSummary:
    """Anonymized aggregate validation metrics for public display."""

    generated_at: datetime
    period_days: int
    benchmark_count: int
    total_validation_points: int
    aggregate_calibration_error: float
    aggregate_brier_score: float
    level_accuracy: tuple[LevelAccuracyRow, ...]
    regime_accuracy: tuple[RegimeAccuracyRow, ...]
    low_confidence_regimes: tuple[str, ...]
    summary: str
    disclaimer: str = (
        "Агрегированная статистика по эталонным рядам. "
        "Не содержит данных конкретных клиентов. "
        "Прошлые результаты не гарантируют будущую доходность."
    )
    forbidden_response_keys: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "email",
                "user_id",
                "profile_id",
                "client_name",
                "deal_intent_id",
            }
        )
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "period_days": self.period_days,
            "benchmark_count": self.benchmark_count,
            "total_validation_points": self.total_validation_points,
            "aggregate_calibration_error": self.aggregate_calibration_error,
            "aggregate_brier_score": self.aggregate_brier_score,
            "level_accuracy": [
                {
                    "level": row.level,
                    "accuracy": row.accuracy,
                    "total_points": row.total_points,
                    "notes": row.notes,
                }
                for row in self.level_accuracy
            ],
            "regime_accuracy": [
                {
                    "regime": row.regime,
                    "accuracy": row.accuracy,
                    "sample_size": row.sample_size,
                    "confidence_note": row.confidence_note,
                }
                for row in self.regime_accuracy
            ],
            "low_confidence_regimes": list(self.low_confidence_regimes),
            "summary": self.summary,
            "disclaimer": self.disclaimer,
        }
