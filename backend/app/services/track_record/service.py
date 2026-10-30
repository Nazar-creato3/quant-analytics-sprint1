"""Public anonymized track record aggregation from hierarchy/replay validation."""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean

from app.services.prediction_hierarchy.hierarchy_validation import HierarchyValidationEngine
from app.services.track_record.reference_series import ReferenceBenchmark, build_reference_benchmarks
from app.services.track_record.types import (
    LevelAccuracyRow,
    PublicTrackRecordSummary,
    RegimeAccuracyRow,
)


_SUMMARY_CACHE: dict = {}


class TrackRecordService:
    """Aggregate replay/hierarchy validation into a public trust summary."""

    LOW_CONFIDENCE_THRESHOLD = 0.55

    def __init__(
        self,
        *,
        hierarchy_engine: HierarchyValidationEngine | None = None,
    ) -> None:
        self._hierarchy = hierarchy_engine or HierarchyValidationEngine()
        self._cacheable = hierarchy_engine is None

    def get_public_summary(
        self,
        *,
        benchmarks: tuple[ReferenceBenchmark, ...] | None = None,
    ) -> PublicTrackRecordSummary:
        """Build anonymized aggregate metrics from reference benchmark series.

        With default benchmarks the result is cached per benchmark set (refreshed hourly
        together with build_reference_benchmarks): the replay is CPU-heavy.
        """
        refs = benchmarks or build_reference_benchmarks()
        cacheable = benchmarks is None and self._cacheable
        if cacheable and _SUMMARY_CACHE.get("refs") is refs:
            return _SUMMARY_CACHE["summary"]
        summary = self._build_summary(refs)
        if cacheable:
            _SUMMARY_CACHE.update(refs=refs, summary=summary)
        return summary

    def _build_summary(self, refs: tuple[ReferenceBenchmark, ...]) -> PublicTrackRecordSummary:
        level_totals: dict[str, list[float]] = {}
        level_points: dict[str, int] = {}
        regime_totals: dict[str, list[float]] = {}
        regime_counts: dict[str, int] = {}
        calibration_errors: list[float] = []
        brier_scores: list[float] = []
        total_points = 0

        for index, benchmark in enumerate(refs):
            instrument_id = 10_000 + index
            volumes = [1.0] * len(benchmark.prices)
            try:
                report = self._hierarchy.run(
                    instrument_id=instrument_id,
                    prices=benchmark.prices,
                    volumes=volumes,
                    sector=benchmark.sector,
                )
            except (ValueError, TypeError):
                continue

            total_points += report.total_points
            calibration_errors.append(report.calibration_error)
            brier_scores.append(report.brier_score)

            for row in report.level_accuracy:
                level_totals.setdefault(row.level, []).append(row.accuracy)
                level_points[row.level] = level_points.get(row.level, 0) + row.total_points

            for regime, stats in report.regime_breakdown.items():
                acc = float(stats.get("accuracy", 0.0))
                count = int(stats.get("total", stats.get("count", 0)))
                regime_totals.setdefault(regime, []).append(acc)
                regime_counts[regime] = regime_counts.get(regime, 0) + count

        level_rows = tuple(
            LevelAccuracyRow(
                level=level,
                accuracy=mean(scores),
                total_points=level_points.get(level, 0),
                notes="aggregated across anonymized benchmarks",
            )
            for level, scores in sorted(level_totals.items())
        )

        regime_rows: list[RegimeAccuracyRow] = []
        low_confidence: list[str] = []
        for regime, scores in sorted(regime_totals.items()):
            accuracy = mean(scores)
            sample = regime_counts.get(regime, 0)
            note = "высокая выборка" if sample >= 30 else "ограниченная выборка"
            if accuracy < self.LOW_CONFIDENCE_THRESHOLD:
                low_confidence.append(regime)
                note = "низкая уверенность — интерпретируйте осторожно"
            regime_rows.append(
                RegimeAccuracyRow(
                    regime=regime,
                    accuracy=accuracy,
                    sample_size=sample,
                    confidence_note=note,
                )
            )

        avg_calibration = mean(calibration_errors) if calibration_errors else 0.0
        avg_brier = mean(brier_scores) if brier_scores else 0.0
        using_synthetic = any(b.is_synthetic for b in refs)
        source_note = (
            "синтетических эталонных рядов"
            if using_synthetic
            else "реальных тикеров (AAPL, MSFT, SPY)"
        )

        return PublicTrackRecordSummary(
            generated_at=datetime.now(timezone.utc),
            period_days=90,
            benchmark_count=len(refs),
            total_validation_points=total_points,
            aggregate_calibration_error=avg_calibration,
            aggregate_brier_score=avg_brier,
            level_accuracy=level_rows,
            regime_accuracy=tuple(regime_rows),
            low_confidence_regimes=tuple(low_confidence),
            summary=(
                f"Агрегированная валидация по {len(refs)} эталонным рядам ({source_note}), "
                f"{total_points} точек. Калибровка {avg_calibration:.3f}, "
                f"Brier {avg_brier:.3f}. "
                "Точность режима — совпадение классификации, не направление цены."
            ),
        )


def get_track_record_service() -> TrackRecordService:
    return TrackRecordService()
