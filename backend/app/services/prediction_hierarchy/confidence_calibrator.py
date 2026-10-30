"""Forecast confidence calibrator (Prompt 37)."""
from __future__ import annotations

from dataclasses import dataclass

from app.services.prediction_hierarchy.global_regime import GlobalMacroRegimeEngine
from app.services.prediction_hierarchy.sector_regime import SectorRegimeEngine
from app.services.prediction_hierarchy.types import (
    GlobalRegimeResult,
    HIGH_CONFIDENCE_THRESHOLD,
    SectorRegimeContext,
)
from app.services.forecast.types import InstrumentForecast


GLOBAL_WEIGHT = 0.35
SECTOR_WEIGHT = 0.25
TICKER_WEIGHT = 0.30
DISPERSION_WEIGHT = 0.10


@dataclass(frozen=True, slots=True)
class CalibrationInput:
    """Confidence sources from all hierarchy levels."""

    ticker_forecast: InstrumentForecast
    global_regime: GlobalRegimeResult | None = None
    sector_regime: SectorRegimeContext | None = None
    scenario_dispersion: float = 0.0
    calibration_error: float | None = None


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    """Calibrated confidence with component breakdown."""

    calibrated_confidence: float
    high_confidence: bool
    global_cap_applied: bool
    components: dict[str, float]
    calibration_error: float | None = None


class ForecastConfidenceCalibrator:
    """Weighted hierarchical confidence aggregation — global dominates when low."""

    def calibrate(self, inputs: CalibrationInput) -> CalibrationResult:
        ticker_conf = inputs.ticker_forecast.confidence
        sector_conf = (
            SectorRegimeEngine.apply_sector_confidence_penalty(
                ticker_conf,
                inputs.sector_regime.regime,
                sector_rotation=inputs.sector_regime.rotation,
            )
            if inputs.sector_regime
            else ticker_conf
        )

        global_conf = inputs.global_regime.confidence if inputs.global_regime else 1.0
        if inputs.global_regime:
            sector_conf = GlobalMacroRegimeEngine.apply_global_confidence_damping(
                sector_conf,
                inputs.global_regime,
            )

        dispersion_penalty = min(0.25, inputs.scenario_dispersion * 2.0)
        weighted = (
            GLOBAL_WEIGHT * global_conf
            + SECTOR_WEIGHT * sector_conf
            + TICKER_WEIGHT * ticker_conf
        ) * (1.0 - dispersion_penalty * DISPERSION_WEIGHT)

        global_cap_applied = False
        if inputs.global_regime and weighted > global_conf:
            weighted = global_conf
            global_cap_applied = True

        calibrated = max(0.0, min(1.0, weighted))
        return CalibrationResult(
            calibrated_confidence=round(calibrated, 4),
            high_confidence=calibrated >= HIGH_CONFIDENCE_THRESHOLD,
            global_cap_applied=global_cap_applied,
            components={
                "ticker_confidence": round(ticker_conf, 4),
                "sector_adjusted_confidence": round(sector_conf, 4),
                "global_confidence": round(global_conf, 4),
                "dispersion_penalty": round(dispersion_penalty, 4),
            },
            calibration_error=inputs.calibration_error,
        )


def compute_brier_score(predictions: list[float], outcomes: list[bool]) -> float:
    """Brier score for probability calibration."""
    if not predictions or len(predictions) != len(outcomes):
        return 0.0
    total = sum((pred - (1.0 if outcome else 0.0)) ** 2 for pred, outcome in zip(predictions, outcomes))
    return round(total / len(predictions), 6)


def compute_calibration_error(
    confidences: list[float],
    outcomes: list[bool],
    *,
    bin_count: int = 5,
) -> float:
    """Mean absolute deviation between confidence bins and actual accuracy."""
    if not confidences or len(confidences) != len(outcomes):
        return 0.0

    bins: list[list[tuple[float, bool]]] = [[] for _ in range(bin_count)]
    for confidence, outcome in zip(confidences, outcomes):
        index = min(bin_count - 1, int(confidence * bin_count))
        bins[index].append((confidence, outcome))

    errors: list[float] = []
    for bucket in bins:
        if not bucket:
            continue
        mean_conf = sum(item[0] for item in bucket) / len(bucket)
        accuracy = sum(1 for item in bucket if item[1]) / len(bucket)
        errors.append(abs(mean_conf - accuracy))

    return round(sum(errors) / len(errors), 6) if errors else 0.0
