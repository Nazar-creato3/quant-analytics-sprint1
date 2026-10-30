"""Full stack integration validation orchestrator (Prompt 30)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping, Sequence

from app.domain.enums import Strategy
from app.domain.profile import ProfileRead
from app.domain.sleeve import SleeveRead
from app.services.control_fabric.replay_engine import ReplayEngine
from app.services.control_fabric.risk_engine import RiskEngine, get_risk_engine
from app.services.control_fabric.risk_types import RiskBudgetContext
from app.services.control_fabric.types import PredictionReplayReport
from app.services.factor.types import FactorName
from app.services.integration.pipeline import (
    ValidationPipeline,
    run_combined_validation,
)
from app.services.integration.report import CombinedValidationReport
from app.services.integration.stack import MIN_HISTORY_BARS, PredictionRiskStack
from app.services.integration.types import HistoricalBar, VenueConfig
from app.services.prediction_hierarchy.hierarchy_validation import HierarchyValidationReport
from app.services.scenario.types import PortfolioPosition, PortfolioSnapshot
from app.services.stress_harness.harness import StressHarness
from app.services.stress_harness.loader import ProfilePortfolioContext
from app.services.stress_harness.types import StressReport

DEFAULT_PERIOD_DAYS = 90
DEFAULT_STRATEGIES = (Strategy.GRID, Strategy.TREND, Strategy.MEAN_REVERSION)
FORWARD_LOSS_THRESHOLD = -0.01
MIN_PROFITABLE_RETURN = 0.001


@dataclass(frozen=True, slots=True)
class RiskGateValidationMetrics:
    """RiskEngine block/allow accuracy vs realized forward returns."""

    total_decisions: int
    blocked_count: int
    allowed_count: int
    false_positive_count: int
    false_negative_count: int
    true_positive_count: int
    true_negative_count: int
    false_positive_rate: float
    false_negative_rate: float

    def summary(self) -> dict[str, float | int]:
        return {
            "total_decisions": self.total_decisions,
            "blocked_count": self.blocked_count,
            "allowed_count": self.allowed_count,
            "false_positive_count": self.false_positive_count,
            "false_negative_count": self.false_negative_count,
            "true_positive_count": self.true_positive_count,
            "true_negative_count": self.true_negative_count,
            "false_positive_rate": self.false_positive_rate,
            "false_negative_rate": self.false_negative_rate,
        }


@dataclass(frozen=True, slots=True)
class FullStackValidationReport:
    """Final validation gate report — not for live auto-promotion."""

    period_days: int
    generated_at: datetime
    deal_intent_report: CombinedValidationReport
    prediction_replay_by_venue: dict[str, PredictionReplayReport]
    risk_gate_metrics: RiskGateValidationMetrics
    stress_report: StressReport
    hierarchy_validation_by_venue: dict[str, HierarchyValidationReport] = field(default_factory=dict)
    validation_gate_passed: bool = False
    modules_connected: tuple[str, ...] = field(
        default_factory=lambda: (
            "market_data",
            "quant_math",
            "regime_engine",
            "sector_regime_engine",
            "global_macro_regime_engine",
            "factor_engine",
            "market_graph",
            "forecast_engine",
            "forecast_output_builder",
            "action_forecast_engine",
            "confidence_calibrator",
            "prediction_hierarchy_orchestrator",
            "marginal_risk_engine",
            "risk_engine",
            "approval_policy_engine",
            "anti_loss_guard",
            "replay_engine",
            "stress_harness",
            "prediction_narrator",
        )
    )

    def summary(self) -> dict[str, object]:
        return {
            "period_days": self.period_days,
            "generated_at": self.generated_at.isoformat(),
            "modules_connected": list(self.modules_connected),
            "deal_intent": self.deal_intent_report.summary(),
            "prediction_replay": {
                source: {
                    "instrument_id": report.instrument_id,
                    "total_points": report.total_points,
                    "regime_accuracy": report.regime_accuracy,
                    "forecast_calibration_correlation": (
                        report.forecast_calibration.confidence_accuracy_correlation
                    ),
                    "risk_breach_rate": report.risk_breach_rate,
                }
                for source, report in self.prediction_replay_by_venue.items()
            },
            "risk_gate_metrics": self.risk_gate_metrics.summary(),
            "stress_harness": self.stress_report.to_dict(),
            "hierarchy_validation": {
                source: report.to_dict()
                for source, report in self.hierarchy_validation_by_venue.items()
            },
            "validation_gate_passed": self.validation_gate_passed,
        }


def compute_risk_gate_accuracy(
    bars_by_instrument: Mapping[int, Sequence[HistoricalBar]],
    venues: Mapping[str, VenueConfig],
    *,
    profile: ProfileRead,
    sleeve: SleeveRead,
    stack: PredictionRiskStack | None = None,
    risk_engine: RiskEngine | None = None,
    min_history: int = MIN_HISTORY_BARS,
    forward_loss_threshold: float = FORWARD_LOSS_THRESHOLD,
    min_profitable_return: float = MIN_PROFITABLE_RETURN,
) -> RiskGateValidationMetrics:
    """Measure RiskEngine false positive/negative rates on historical bars."""
    stack_builder = stack or PredictionRiskStack()
    engine = risk_engine or get_risk_engine()
    budget = RiskBudgetContext(
        diversification_policy=profile.diversification_policy or {},
        max_drawdown_pct=float(profile.max_drawdown_pct),
        sleeve_risk_budget=sleeve.risk_budget,
        profile_max_daily_loss=profile.max_daily_loss_abs,
    )

    false_positive = 0
    false_negative = 0
    true_positive = 0
    true_negative = 0
    blocked_count = 0
    allowed_count = 0

    for venue in venues.values():
        bars = list(bars_by_instrument.get(venue.instrument_id, ()))
        if len(bars) < min_history + 1:
            continue

        for index in range(min_history, len(bars) - 1):
            try:
                context = stack_builder.build_at_index(
                    bars_by_instrument,
                    target=venue,
                    index=index,
                    profile=profile,
                    sleeve=sleeve,
                )
            except (IndexError, ValueError):
                continue

            assessment = engine.assess(context.risk_inputs, budget)
            blocked = len(assessment.breached) > 0

            entry = bars[index].close
            exit_price = bars[index + 1].close
            if entry <= 0:
                continue
            forward_return = (exit_price - entry) / entry

            if blocked:
                blocked_count += 1
                if forward_return > min_profitable_return:
                    false_positive += 1
                else:
                    true_positive += 1
            else:
                allowed_count += 1
                if forward_return < forward_loss_threshold:
                    false_negative += 1
                else:
                    true_negative += 1

    total = blocked_count + allowed_count
    return RiskGateValidationMetrics(
        total_decisions=total,
        blocked_count=blocked_count,
        allowed_count=allowed_count,
        false_positive_count=false_positive,
        false_negative_count=false_negative,
        true_positive_count=true_positive,
        true_negative_count=true_negative,
        false_positive_rate=(false_positive / blocked_count if blocked_count else 0.0),
        false_negative_rate=(false_negative / allowed_count if allowed_count else 0.0),
    )


async def run_full_stack_validation(
    profile: ProfileRead,
    sleeves: Mapping[str, SleeveRead],
    venues: Mapping[str, VenueConfig],
    venue_bars: Mapping[str, tuple[list[HistoricalBar], bool]],
    *,
    pipeline: ValidationPipeline | None = None,
    period_days: int = DEFAULT_PERIOD_DAYS,
    strategies: Sequence[Strategy] = DEFAULT_STRATEGIES,
    stack: PredictionRiskStack | None = None,
    replay_engine: ReplayEngine | None = None,
    stress_harness: StressHarness | None = None,
) -> FullStackValidationReport:
    """Run end-to-end validation across prediction, risk, and control stack."""
    primary_sleeve = next(iter(sleeves.values()))
    validation_pipeline = pipeline or ValidationPipeline(profile, primary_sleeve)
    stack_builder = stack or PredictionRiskStack()
    replay = replay_engine or ReplayEngine()
    harness = stress_harness or StressHarness()

    bars_by_instrument: dict[int, list[HistoricalBar]] = {}
    for source, (bars, _stub) in venue_bars.items():
        venue = venues[source]
        bars_by_instrument[venue.instrument_id] = bars

    deal_intent_report = await run_combined_validation(
        validation_pipeline,
        dict(venue_bars),
        venues=venues,
        strategies=strategies,
        period_days=period_days,
        stack=stack_builder,
        bars_by_instrument=bars_by_instrument,
    )

    prediction_replay: dict[str, PredictionReplayReport] = {}
    for source, (bars, _stub) in venue_bars.items():
        venue = venues[source]
        if len(bars) < MIN_HISTORY_BARS + 10:
            continue
        prices = [bar.close for bar in bars]
        volumes = [bar.volume for bar in bars]
        timestamps = [bar.timestamp.isoformat() for bar in bars]
        prediction_replay[source] = replay.replay_predictions(
            instrument_id=venue.instrument_id,
            prices=prices,
            volumes=volumes,
            timestamps=timestamps,
            forward_horizon=10,
            min_history=MIN_HISTORY_BARS,
        )

    risk_metrics = compute_risk_gate_accuracy(
        bars_by_instrument,
        venues,
        profile=profile,
        sleeve=primary_sleeve,
        stack=stack_builder,
    )

    portfolio_context = _build_portfolio_context(
        profile,
        sleeves,
        bars_by_instrument,
        venues,
    )
    stress_report = harness.run_all_scenarios(portfolio_context)

    hierarchy_validation: dict[str, HierarchyValidationReport] = {}
    for source, (bars, _stub) in venue_bars.items():
        venue = venues[source]
        if len(bars) < MIN_HISTORY_BARS + 10:
            continue
        hierarchy_validation[source] = replay.replay_hierarchy(
            instrument_id=venue.instrument_id,
            prices=[bar.close for bar in bars],
            volumes=[bar.volume for bar in bars],
            forward_horizon=10,
            min_history=MIN_HISTORY_BARS,
        )

    gate_passed = _evaluate_validation_gate(
        prediction_replay,
        risk_metrics,
        hierarchy_validation,
        period_days=period_days,
    )

    return FullStackValidationReport(
        period_days=period_days,
        generated_at=datetime.now(timezone.utc),
        deal_intent_report=deal_intent_report,
        prediction_replay_by_venue=prediction_replay,
        risk_gate_metrics=risk_metrics,
        stress_report=stress_report,
        hierarchy_validation_by_venue=hierarchy_validation,
        validation_gate_passed=gate_passed,
    )


def _evaluate_validation_gate(
    prediction_replay: dict[str, PredictionReplayReport],
    risk_metrics: RiskGateValidationMetrics,
    hierarchy_validation: dict[str, HierarchyValidationReport],
    *,
    period_days: int,
) -> bool:
    """90-day validation gate — honest thresholds, not auto-live promotion."""
    if period_days < 60:
        return False
    if not prediction_replay:
        return False
    avg_regime_accuracy = sum(r.regime_accuracy for r in prediction_replay.values()) / len(
        prediction_replay
    )
    if avg_regime_accuracy < 0.25:
        return False
    if risk_metrics.false_negative_rate > 0.85:
        return False
    if hierarchy_validation:
        avg_calibration = sum(r.calibration_error for r in hierarchy_validation.values()) / len(
            hierarchy_validation
        )
        if avg_calibration > 0.45:
            return False
    return True


def _build_portfolio_context(
    profile: ProfileRead,
    sleeves: Mapping[str, SleeveRead],
    bars_by_instrument: Mapping[int, Sequence[HistoricalBar]],
    venues: Mapping[str, VenueConfig],
) -> ProfilePortfolioContext:
    from app.services.market_graph.builder import returns_from_closes

    positions: list[PortfolioPosition] = []
    returns_by_instrument: dict[int, list[float]] = {}
    sector_by_instrument: dict[int, str] = {}
    factor_exposures: dict[int, dict[FactorName, float]] = {}
    stack = PredictionRiskStack()

    venue_list = list(venues.values())
    equal_weight = 1.0 / len(venue_list) if venue_list else 1.0
    primary_sleeve = next(iter(sleeves.values()))

    for venue in venue_list:
        bars = list(bars_by_instrument.get(venue.instrument_id, ()))
        if not bars:
            continue
        positions.append(
            PortfolioPosition(
                instrument_id=venue.instrument_id,
                sleeve_id=venue.sleeve_id,
                weight=equal_weight,
            )
        )
        series = returns_from_closes([bar.close for bar in bars])
        if series:
            returns_by_instrument[venue.instrument_id] = series
        try:
            context = stack.build_at_index(
                bars_by_instrument,
                target=venue,
                index=len(bars) - 1,
                profile=profile,
                sleeve=sleeves.get(venue.sleeve_id, primary_sleeve),
            )
            factor_exposures[venue.instrument_id] = context.factor_exposures
            sector_by_instrument[venue.instrument_id] = (
                context.risk_inputs.sector_by_instrument.get(
                    venue.instrument_id,
                    "unknown",
                )
            )
        except (IndexError, ValueError):
            factor_exposures[venue.instrument_id] = {}
            sector_by_instrument[venue.instrument_id] = "unknown"

    portfolio = PortfolioSnapshot(
        positions=tuple(positions),
        factor_exposures=factor_exposures,
        returns_by_instrument=returns_by_instrument,
        sector_by_instrument=sector_by_instrument or None,
    )
    return ProfilePortfolioContext(
        profile_id=profile.id,
        portfolio=portfolio,
        sleeve_risk_budgets={sleeve.id: sleeve.risk_budget for sleeve in sleeves.values()},
        portfolio_value_usd=100_000.0,
        sleeves=tuple(sleeves.values()),
    )
