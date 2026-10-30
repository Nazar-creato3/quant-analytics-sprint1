"""Full hierarchy validation report (Prompt 40)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence

from app.services.control_fabric.replay_validation import infer_actual_regime_from_forward_prices
from app.services.prediction_hierarchy.action_forecast import ActionForecastContext, ActionForecastEngine
from app.services.prediction_hierarchy.calibration_tracker import (
    CalibrationRunSnapshot,
    record_validation_pairs,
)
from app.services.prediction_hierarchy.confidence_calibrator import (
    CalibrationInput,
    ForecastConfidenceCalibrator,
    compute_brier_score,
    compute_calibration_error,
)
from app.services.prediction_hierarchy.forecast_output import ForecastOutputBuilder
from app.services.prediction_hierarchy.global_regime import GlobalMacroRegimeEngine, MacroIndicatorSnapshot
from app.services.prediction_hierarchy.sector_regime import SectorRegimeEngine
from app.services.prediction_hierarchy.types import ActionRecommendation
from app.services.regime.engine import RegimeEngine
from app.services.regime.features import prices_to_returns
from app.services.regime.types import InstrumentSeries


@dataclass(frozen=True, slots=True)
class HierarchyLevelAccuracy:
    level: str
    accuracy: float
    total_points: int
    notes: str = ""


@dataclass(frozen=True, slots=True)
class ActionForecastHitRate:
    recommendation: str
    count: int
    hit_rate: float
    description: str


@dataclass(frozen=True, slots=True)
class RollingWindowMetric:
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
            # Deprecated alias — measures regime-label match, not price direction.
            "directional_accuracy": self.regime_match_accuracy,
            "mae": self.mae,
            "sample_size": self.sample_size,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
        }


@dataclass(frozen=True, slots=True)
class HierarchyValidationReport:
    """Honest multi-level validation — not a single headline accuracy."""

    period_days: int
    generated_at: datetime
    instrument_id: int
    total_points: int
    level_accuracy: tuple[HierarchyLevelAccuracy, ...]
    calibration_error: float
    brier_score: float
    calibration_error_by_shock: dict[str, float]
    action_distribution: dict[str, int]
    action_hit_rates: tuple[ActionForecastHitRate, ...]
    regime_breakdown: dict[str, dict[str, float]]
    summary: str
    calibration_error_series: tuple[float, ...] = ()
    rolling_window_metrics: tuple[RollingWindowMetric, ...] = ()
    validation_confidences: tuple[float, ...] = ()
    validation_outcomes: tuple[bool, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "period_days": self.period_days,
            "generated_at": self.generated_at.isoformat(),
            "instrument_id": self.instrument_id,
            "total_points": self.total_points,
            "level_accuracy": [
                {
                    "level": item.level,
                    "accuracy": item.accuracy,
                    "total_points": item.total_points,
                    "notes": item.notes,
                }
                for item in self.level_accuracy
            ],
            "calibration_error": self.calibration_error,
            "brier_score": self.brier_score,
            "calibration_error_by_shock": self.calibration_error_by_shock,
            "calibration_error_series": list(self.calibration_error_series),
            "rolling_window_metrics": [m.to_dict() for m in self.rolling_window_metrics],
            "action_distribution": self.action_distribution,
            "action_hit_rates": [
                {
                    "recommendation": item.recommendation,
                    "count": item.count,
                    "hit_rate": item.hit_rate,
                    "description": item.description,
                }
                for item in self.action_hit_rates
            ],
            "regime_breakdown": self.regime_breakdown,
            "summary": self.summary,
        }


_ACTION_HIT_DESCRIPTIONS: dict[str, str] = {
    ActionRecommendation.WAIT.value: "wait preceded drawdown (would-have-entered loss)",
    ActionRecommendation.AVOID.value: "avoid — conservative stance (always credited)",
    ActionRecommendation.REDUCE_SIZE.value: "reduce preceded elevated drawdown or vol",
    ActionRecommendation.HEDGE.value: "hedge preceded elevated forward volatility",
    ActionRecommendation.HOLD.value: "hold matched moderate forward move",
    ActionRecommendation.ENTER_SMALL_SIZE.value: "small entry preceded positive forward return",
    ActionRecommendation.ENTER_NORMAL_SIZE.value: "normal entry preceded strong forward return",
}


def _action_recommendation_hit(
    recommendation: str,
    *,
    forward_return: float,
    forward_vol: float,
) -> bool:
    if recommendation == ActionRecommendation.WAIT.value:
        return forward_return < 0.0
    if recommendation == ActionRecommendation.AVOID.value:
        return True
    if recommendation == ActionRecommendation.REDUCE_SIZE.value:
        return forward_return < 0.02 or forward_vol > 0.02
    if recommendation == ActionRecommendation.HEDGE.value:
        return forward_vol > 0.015
    if recommendation == ActionRecommendation.HOLD.value:
        return abs(forward_return) < 0.05
    if recommendation == ActionRecommendation.ENTER_SMALL_SIZE.value:
        return forward_return > 0.0
    if recommendation == ActionRecommendation.ENTER_NORMAL_SIZE.value:
        return forward_return > 0.01
    return False


class HierarchyValidationEngine:
    """Replay hierarchy levels with forward return validation."""

    def __init__(
        self,
        *,
        regime_engine: RegimeEngine | None = None,
        sector_engine: SectorRegimeEngine | None = None,
        global_engine: GlobalMacroRegimeEngine | None = None,
        action_engine: ActionForecastEngine | None = None,
        calibrator: ForecastConfidenceCalibrator | None = None,
        output_builder: ForecastOutputBuilder | None = None,
        forecast_engine: "ForecastEngine | None" = None,
    ) -> None:
        from app.services.forecast.engine import get_forecast_engine

        self._regime_engine = regime_engine or RegimeEngine()
        self._sector_engine = sector_engine or SectorRegimeEngine(regime_engine=self._regime_engine)
        self._global_engine = global_engine or GlobalMacroRegimeEngine()
        self._action_engine = action_engine or ActionForecastEngine()
        self._calibrator = calibrator or ForecastConfidenceCalibrator()
        self._output_builder = output_builder or ForecastOutputBuilder()
        self._forecast_engine = forecast_engine or get_forecast_engine()

    def run(
        self,
        *,
        instrument_id: int,
        prices: Sequence[float],
        volumes: Sequence[float] | None = None,
        sector: str = "technology",
        forward_horizon: int = 10,
        min_history: int = 30,
        macro_indicators: MacroIndicatorSnapshot | None = None,
        macro_snapshots: Sequence[MacroIndicatorSnapshot] | None = None,
        sector_instruments: Mapping[int, InstrumentSeries] | None = None,
        rolling_calibration_window: int = 20,
    ) -> HierarchyValidationReport:
        price_list = list(prices)
        volume_list = list(volumes) if volumes else None
        if len(price_list) < min_history + forward_horizon:
            raise ValueError("insufficient history for hierarchy validation")

        default_macro = macro_indicators or MacroIndicatorSnapshot(vix=22.0)
        sector_map = dict(sector_instruments or {})
        if not sector_map:
            sector_map = {
                instrument_id: InstrumentSeries(
                    prices=price_list,
                    volumes=volume_list or [0.0] * len(price_list),
                )
            }

        global_matches: list[bool] = []
        sector_matches: list[bool] = []
        forecast_matches: list[bool] = []
        confidences: list[float] = []
        outcomes: list[bool] = []
        rolling_calibration_errors: list[float] = []
        shock_confidences: dict[str, list[float]] = {"normal": [], "shock": []}
        shock_outcomes: dict[str, list[bool]] = {"normal": [], "shock": []}
        action_records: dict[str, list[bool]] = {}
        action_counts: dict[str, int] = {}
        regime_breakdown: dict[str, dict[str, float]] = {}

        last_index = len(price_list) - forward_horizon
        for index in range(min_history - 1, last_index):
            history = price_list[: index + 1]
            forward = price_list[index + 1 : index + 1 + forward_horizon]
            history_volumes = volume_list[: index + 1] if volume_list else None

            macro = (
                macro_snapshots[index]
                if macro_snapshots is not None and index < len(macro_snapshots)
                else default_macro
            )

            instrument_regime = self._regime_engine.classify_instrument(history, history_volumes)
            actual_regime = infer_actual_regime_from_forward_prices(
                forward,
                regime_engine=self._regime_engine,
            )
            forecast_matches.append(instrument_regime.dominant_regime == actual_regime)

            sector_history: dict[int, InstrumentSeries] = {}
            for iid, series in sector_map.items():
                end = min(index + 1, len(series.prices))
                vols = series.volumes[:end] if series.volumes else [0.0] * end
                sector_history[iid] = InstrumentSeries(
                    prices=series.prices[:end],
                    volumes=vols,
                    spread_bps=series.spread_bps,
                )
            market_prices = self._sector_engine.aggregate_market_prices({sector: sector_history})
            sector_ctx = self._sector_engine.classify_sector_regime(
                sector,
                sector_history,
                market_prices=market_prices or history,
            )
            sector_matches.append(sector_ctx.regime.dominant_regime == actual_regime)

            global_result = self._global_engine.classify(macro)
            risk_on_actual = actual_regime in {"bullish_trend", "choppy_range"}
            risk_on_pred = global_result.dominant_regime == "risk_on"
            global_matches.append(risk_on_pred == risk_on_actual)

            returns = prices_to_returns(history)
            scenario_dispersion = abs(max(returns[-10:]) - min(returns[-10:])) if len(returns) >= 10 else 0.0
            from app.services.forecast.types import ForecastInputBundle

            bundle = ForecastInputBundle(
                instrument_id=instrument_id,
                prices=list(history),
                volumes=list(history_volumes) if history_volumes else None,
                regime_result=instrument_regime,
            )
            ticker_forecast = self._forecast_engine.compute_from_inputs(bundle)
            calibration = self._calibrator.calibrate(
                CalibrationInput(
                    ticker_forecast=ticker_forecast,
                    global_regime=global_result,
                    sector_regime=sector_ctx,
                    scenario_dispersion=scenario_dispersion,
                )
            )
            confidences.append(calibration.calibrated_confidence)
            outcome = forecast_matches[-1]
            outcomes.append(outcome)

            if len(confidences) >= rolling_calibration_window:
                window_conf = confidences[-rolling_calibration_window:]
                window_out = outcomes[-rolling_calibration_window:]
                rolling_calibration_errors.append(
                    compute_calibration_error(window_conf, window_out)
                )

            shock_key = "shock" if actual_regime == "high_volatility_shock" else "normal"
            shock_confidences[shock_key].append(calibration.calibrated_confidence)
            shock_outcomes[shock_key].append(outcome)

            action = self._action_engine.evaluate(
                ActionForecastContext(
                    calibrated_confidence=calibration.calibrated_confidence,
                    composite_risk_score=ticker_forecast.composite_risk_score,
                    scenario_dispersion=scenario_dispersion,
                    global_regime=global_result,
                    sector_regime=sector_ctx,
                )
            )
            action_counts[action.recommendation.value] = (
                action_counts.get(action.recommendation.value, 0) + 1
            )
            forward_return = (forward[-1] - history[-1]) / history[-1] if history[-1] > 0 else 0.0
            forward_returns = prices_to_returns(forward) if len(forward) >= 2 else [forward_return]
            forward_vol = (
                (sum(r * r for r in forward_returns) / len(forward_returns)) ** 0.5
                if forward_returns
                else abs(forward_return)
            )
            hit = _action_recommendation_hit(
                action.recommendation.value,
                forward_return=forward_return,
                forward_vol=forward_vol,
            )
            action_records.setdefault(action.recommendation.value, []).append(hit)

            bucket = regime_breakdown.setdefault(actual_regime, {"correct": 0.0, "total": 0.0})
            bucket["total"] += 1
            if forecast_matches[-1]:
                bucket["correct"] += 1

        total = len(forecast_matches)
        calibration_error = compute_calibration_error(confidences, outcomes)
        brier = compute_brier_score(confidences, outcomes)
        record_validation_pairs(confidences, outcomes)

        shock_calibration = {
            key: compute_calibration_error(shock_confidences[key], shock_outcomes[key])
            for key in ("normal", "shock")
            if shock_confidences[key]
        }

        action_hit_rates = tuple(
            ActionForecastHitRate(
                recommendation=label,
                count=len(records),
                hit_rate=sum(records) / len(records) if records else 0.0,
                description=_ACTION_HIT_DESCRIPTIONS.get(label, "action-specific hit rate"),
            )
            for label, records in sorted(action_records.items())
        )

        for regime, stats in regime_breakdown.items():
            if stats["total"] > 0:
                stats["accuracy"] = stats["correct"] / stats["total"]

        rolling_metrics: list[RollingWindowMetric] = []
        for window in (30, 90, 365):
            if total < window // 3:
                continue
            tail_matches = forecast_matches[-window:]
            tail_conf = confidences[-window:]
            tail_out = outcomes[-window:]
            acc = sum(tail_matches) / len(tail_matches) if tail_matches else 0.5
            mae = compute_calibration_error(tail_conf, tail_out) if tail_conf else calibration_error
            hits = sum(1 for m in tail_matches if m)
            from app.utils.wilson_ci import wilson_ci

            interval = wilson_ci(hits, len(tail_matches)) if tail_matches else None
            rolling_metrics.append(
                RollingWindowMetric(
                    window_days=window,
                    regime_match_accuracy=round(acc, 4),
                    mae=round(mae, 4),
                    sample_size=len(tail_matches),
                    ci_low=round(interval.ci_low, 4) if interval else None,
                    ci_high=round(interval.ci_high, 4) if interval else None,
                )
            )

        summary = (
            f"Hierarchy validation over {total} points: instrument regime "
            f"{sum(forecast_matches)/total:.1%}, sector {sum(sector_matches)/total:.1%}, "
            f"global {sum(global_matches)/total:.1%}. Calibration error {calibration_error:.3f} "
            f"(shock periods {shock_calibration.get('shock', 'n/a')}). "
            "Higher uncertainty in shock regimes is expected."
        )

        return HierarchyValidationReport(
            period_days=max(1, total // 5),
            generated_at=datetime.now(timezone.utc),
            instrument_id=instrument_id,
            total_points=total,
            level_accuracy=(
                HierarchyLevelAccuracy(
                    "global_regime",
                    sum(global_matches) / total,
                    total,
                    "risk_on vs forward behavior",
                ),
                HierarchyLevelAccuracy(
                    "sector_regime",
                    sum(sector_matches) / total,
                    total,
                    "true sector aggregate",
                ),
                HierarchyLevelAccuracy(
                    "instrument_regime",
                    sum(forecast_matches) / total,
                    total,
                ),
            ),
            calibration_error=calibration_error,
            brier_score=brier,
            calibration_error_by_shock=shock_calibration,
            action_distribution=action_counts,
            action_hit_rates=action_hit_rates,
            regime_breakdown=regime_breakdown,
            summary=summary,
            calibration_error_series=tuple(rolling_calibration_errors),
            rolling_window_metrics=tuple(rolling_metrics),
            validation_confidences=tuple(confidences),
            validation_outcomes=tuple(outcomes),
        )

    def snapshot_for_persist(self, report: HierarchyValidationReport) -> CalibrationRunSnapshot:
        return CalibrationRunSnapshot(
            calibration_error=report.calibration_error,
            brier_score=report.brier_score,
            total_points=report.total_points,
            period_days=report.period_days,
        )
