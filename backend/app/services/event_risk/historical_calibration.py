"""Historical calibration path for news impact (Prompt 24)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.services.event_risk.news_impact import (
    NewsImpactAnalog,
    compute_analog_probability,
    compute_news_impact_probability,
)


@dataclass(frozen=True, slots=True)
class HistoricalCalibrationResult:
    """Calibration output from news_impact_history analogs."""

    probability: float
    analog_count: int
    strong_analog_count: int
    posterior_from_history: float
    calibrated: bool


class NewsImpactHistoricalCalibrator:
    """Load historical analogs and calibrate news_impact_probability."""

    def calibrate_from_history(
        self,
        *,
        topic_tags: Sequence[str],
        factor_exposures: dict[str, float],
        history: Sequence[NewsImpactAnalog],
        daily_volatility: float,
        sigma_threshold: float = 2.0,
    ) -> HistoricalCalibrationResult:
        result = compute_news_impact_probability(
            topic_tags=topic_tags,
            factor_exposures=factor_exposures,
            history=history,
            daily_volatility=daily_volatility,
            sigma_threshold=sigma_threshold,
        )
        posterior, analog_count, strong_count = compute_analog_probability(topic_tags, history)
        return HistoricalCalibrationResult(
            probability=result.probability,
            analog_count=analog_count,
            strong_analog_count=strong_count,
            posterior_from_history=posterior,
            calibrated=analog_count >= 3,
        )

    @staticmethod
    def history_from_records(
        records: Sequence[dict[str, object]],
    ) -> tuple[NewsImpactAnalog, ...]:
        analogs: list[NewsImpactAnalog] = []
        for record in records:
            tags = record.get("topic_tags") or record.get("tags") or ()
            if isinstance(tags, str):
                tags = tuple(part.strip() for part in tags.split(",") if part.strip())
            analogs.append(
                NewsImpactAnalog(
                    topic_tags=tuple(tags),
                    strong_move=bool(record.get("strong_move", False)),
                    predicted_probability=record.get("predicted_probability"),
                )
            )
        return tuple(analogs)
