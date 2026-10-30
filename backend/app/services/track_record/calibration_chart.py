"""Calibration reliability diagram and rolling accuracy for track record display."""
from __future__ import annotations

from dataclasses import dataclass

from app.services.track_record.reference_series import ReferenceBenchmark, build_reference_benchmarks
from app.services.prediction_hierarchy.hierarchy_validation import HierarchyValidationEngine


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    predicted_confidence: float
    observed_frequency: float
    count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "predicted_confidence": self.predicted_confidence,
            "observed_frequency": self.observed_frequency,
            "count": self.count,
        }


@dataclass(frozen=True, slots=True)
class RollingAccuracyPoint:
    window_days: int
    regime_match_accuracy: float
    mae: float
    sample_size: int
    ci_low: float | None = None
    ci_high: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "window_days": self.window_days,
            "regime_match_accuracy": self.regime_match_accuracy,
            # Deprecated alias — regime-label match, not price up/down.
            "directional_accuracy": self.regime_match_accuracy,
            "mae": self.mae,
            "sample_size": self.sample_size,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
        }


@dataclass(frozen=True, slots=True)
class TrackRecordChartData:
    calibration_bins: tuple[CalibrationBin, ...]
    rolling_accuracy: tuple[RollingAccuracyPoint, ...]
    aggregate_calibration_error: float | None
    drift_flag: bool
    data_source: str
    disclaimer_ru: str

    def to_dict(self) -> dict[str, object]:
        return {
            "calibration_bins": [b.to_dict() for b in self.calibration_bins],
            "rolling_accuracy": [p.to_dict() for p in self.rolling_accuracy],
            "aggregate_calibration_error": self.aggregate_calibration_error,
            # Deprecated alias — was mislabeled as live-vs-backtest gap.
            "live_vs_backtest_gap": self.aggregate_calibration_error,
            "drift_flag": self.drift_flag,
            "data_source": self.data_source,
            "disclaimer_ru": self.disclaimer_ru,
        }


def _build_calibration_bins(
    confidences: list[float],
    outcomes: list[bool],
    *,
    n_bins: int = 5,
) -> tuple[CalibrationBin, ...]:
    if not confidences:
        return ()
    bins: list[CalibrationBin] = []
    for i in range(n_bins):
        lo = i / n_bins
        hi = (i + 1) / n_bins
        mid = (lo + hi) / 2
        mask = [lo <= c < hi or (i == n_bins - 1 and c == 1.0) for c in confidences]
        subset_out = [outcomes[j] for j, m in enumerate(mask) if m]
        if not subset_out:
            continue
        observed = sum(subset_out) / len(subset_out)
        bins.append(
            CalibrationBin(
                predicted_confidence=round(mid, 2),
                observed_frequency=round(observed, 3),
                count=len(subset_out),
            )
        )
    return tuple(bins)


def _track_record_disclaimer(*, using_synthetic: bool) -> str:
    if using_synthetic:
        return (
            "Предварительная статистика на синтетических тестовых рядах — не финальная. "
            "Метрика «точность режима» — совпадение классификации режима, не направление цены."
        )
    return (
        "Walk-forward валидация по реальным дневным рядам (AAPL, MSFT, SPY). "
        "«Точность режима» — совпадение классификации режима на горизонте, не направление цены."
    )


def build_track_record_chart_data(
    *,
    benchmarks: tuple[ReferenceBenchmark, ...] | None = None,
) -> TrackRecordChartData:
    """Aggregate calibration bins and rolling regime-match accuracy across benchmarks."""
    refs = benchmarks or build_reference_benchmarks()
    using_synthetic = any(b.is_synthetic for b in refs)
    data_source = "synthetic_fallback" if using_synthetic else "real_tickers"

    engine = HierarchyValidationEngine()

    all_confidences: list[float] = []
    all_outcomes: list[bool] = []
    rolling_points: list[RollingAccuracyPoint] = []
    calibration_errors: list[float] = []

    for index, benchmark in enumerate(refs):
        instrument_id = 10_000 + index
        volumes = [1.0] * len(benchmark.prices)
        try:
            report = engine.run(
                instrument_id=instrument_id,
                prices=benchmark.prices,
                volumes=volumes,
                sector=benchmark.sector,
            )
        except (ValueError, TypeError):
            continue

        calibration_errors.append(report.calibration_error)

        if report.rolling_window_metrics:
            for metric in report.rolling_window_metrics:
                rolling_points.append(
                    RollingAccuracyPoint(
                        window_days=metric.window_days,
                        regime_match_accuracy=metric.regime_match_accuracy,
                        mae=metric.mae,
                        sample_size=metric.sample_size,
                        ci_low=metric.ci_low,
                        ci_high=metric.ci_high,
                    )
                )
        else:
            for window in (30, 90, 365):
                if report.total_points >= window // 3:
                    acc = next(
                        (la.accuracy for la in report.level_accuracy if la.level == "instrument_regime"),
                        0.5,
                    )
                    rolling_points.append(
                        RollingAccuracyPoint(
                            window_days=window,
                            regime_match_accuracy=acc,
                            mae=report.calibration_error,
                            sample_size=min(report.total_points, window),
                        )
                    )

        if report.validation_confidences and report.validation_outcomes:
            all_confidences.extend(report.validation_confidences)
            all_outcomes.extend(report.validation_outcomes)

    bins = _build_calibration_bins(all_confidences, all_outcomes)

    avg_cal = sum(calibration_errors) / len(calibration_errors) if calibration_errors else 0.0
    aggregate_cal = avg_cal if calibration_errors else None
    drift_flag = aggregate_cal is not None and aggregate_cal > 0.15

    return TrackRecordChartData(
        calibration_bins=bins,
        rolling_accuracy=tuple(rolling_points),
        aggregate_calibration_error=aggregate_cal,
        drift_flag=drift_flag,
        data_source=data_source,
        disclaimer_ru=_track_record_disclaimer(using_synthetic=using_synthetic),
    )
