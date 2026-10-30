"""ReplayEngine — reproduce system decisions from saved intents and market data."""
from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from app.domain.deal_intent import DealIntentRead
from app.domain.profile import ProfileRead
from app.domain.sleeve import SleeveRead
from app.services.approval.engine import evaluate_policy
from app.services.approval.models import MarketContext, PolicyDecision
from app.services.control_fabric.replay_validation import (
    build_regime_confusion_matrix,
    compute_forecast_calibration,
    infer_actual_regime_from_forward_prices,
    regime_classification_accuracy,
)
from app.services.control_fabric.risk_engine import RiskEngine
from app.services.control_fabric.risk_gate import RiskGate
from app.services.control_fabric.risk_types import RiskBudgetContext, RiskEngineInput
from app.services.control_fabric.types import (
    ForecastCalibrationBin,
    ForecastCalibrationReport,
    OpenPositionExposure,
    PredictionReplayPoint,
    PredictionReplayReport,
    RegimeConfusionMatrix,
    ReplayDecisionRecord,
    ReplayIntentRecord,
    ReplayReport,
    RiskSnapshot,
)
from app.services.forecast.engine import ForecastEngine
from app.services.forecast.types import ForecastDirection, ForecastInputBundle, ForecastSignals
from app.services.forecast.aggregation import aggregate_forecast
from app.services.regime.engine import RegimeEngine
from app.services.regime.features import prices_to_returns
from app.services.regime.types import ALL_REGIME_LABELS


class ReplayEngine:
    """Re-run RiskGate + ApprovalPolicyEngine on historical snapshots."""

    def __init__(
        self,
        *,
        risk_gate: RiskGate | None = None,
        regime_engine: RegimeEngine | None = None,
        forecast_engine: ForecastEngine | None = None,
        risk_engine: RiskEngine | None = None,
    ) -> None:
        self._risk_gate = risk_gate or RiskGate()
        self._regime_engine = regime_engine or RegimeEngine()
        self._forecast_engine = forecast_engine or ForecastEngine(regime_engine=self._regime_engine)
        self._risk_engine = risk_engine or RiskEngine()

    def replay(
        self,
        records: Sequence[ReplayIntentRecord],
        *,
        profiles: dict[str, ProfileRead],
        sleeves: dict[str, SleeveRead],
        expected_decisions: dict[str, dict[str, str]] | None = None,
        open_positions_by_intent: dict[str, Sequence[OpenPositionExposure]] | None = None,
    ) -> ReplayReport:
        decisions: list[ReplayDecisionRecord] = []
        matched = 0
        mismatched = 0

        for record in records:
            profile = profiles[record.profile_id]
            sleeve = sleeves[record.sleeve_id]
            intent = DealIntentRead.model_validate(record.intent_snapshot)
            context = self._context_from_snapshot(record.market_snapshot)
            snapshot = self._risk_snapshot_from_snapshot(record.market_snapshot)
            positions = (open_positions_by_intent or {}).get(record.intent_id, ())

            risk_result = self._risk_gate.check_intent(
                intent,
                profile,
                sleeve,
                context,
                snapshot=snapshot,
                open_positions=positions,
                instrument_correlations=record.market_snapshot.get("instrument_correlations"),
                atr=float(record.market_snapshot.get("atr", 0.0)),
                price=float(record.market_snapshot.get("price", 0.0)),
            )

            approval: PolicyDecision | None = None
            if risk_result.allowed:
                approval = evaluate_policy(intent, profile, context)

            expected = (expected_decisions or {}).get(record.intent_id, {})
            risk_outcome = risk_result.outcome.value
            approval_state = approval.state.value if approval else "blocked_by_risk_gate"
            exp_risk = expected.get("risk_gate_outcome", risk_outcome)
            exp_approval = expected.get("approval_state", approval_state)
            is_match = risk_outcome == exp_risk and approval_state == exp_approval
            if is_match:
                matched += 1
            else:
                mismatched += 1

            decisions.append(
                ReplayDecisionRecord(
                    intent_id=record.intent_id,
                    risk_gate={
                        "outcome": risk_outcome,
                        "allowed": risk_result.allowed,
                        "reason": risk_result.reason,
                    },
                    approval_decision=(
                        approval.to_audit_details()
                        if approval
                        else {"policy_state": "blocked_by_risk_gate", "reason": risk_result.reason}
                    ),
                    matched=is_match,
                    notes="" if is_match else f"expected risk={exp_risk} approval={exp_approval}",
                )
            )

        return ReplayReport(
            total=len(records),
            matched=matched,
            mismatched=mismatched,
            decisions=tuple(decisions),
        )

    def replay_predictions(
        self,
        *,
        instrument_id: int,
        prices: Sequence[float],
        volumes: Sequence[float] | None = None,
        spread_bps: float | None = None,
        timestamps: Sequence[str] | None = None,
        forward_horizon: int = 10,
        min_history: int = 30,
        correlation_cluster: float = 0.0,
        risk_budget: RiskBudgetContext | None = None,
        calibration_bins: int = 5,
    ) -> PredictionReplayReport:
        """Replay RegimeEngine/ForecastEngine/RiskEngine with forward validation."""
        price_list = list(prices)
        volume_list = list(volumes) if volumes is not None else None
        timestamp_list = list(timestamps) if timestamps is not None else None

        if len(price_list) < min_history + forward_horizon:
            raise ValueError(
                "insufficient price history: need at least "
                f"{min_history + forward_horizon} bars"
            )

        budget = risk_budget or RiskBudgetContext(
            diversification_policy={},
            max_drawdown_pct=15.0,
            sleeve_risk_budget=Decimal("10000"),
            profile_max_daily_loss=Decimal("5000"),
        )

        points: list[PredictionReplayPoint] = []
        predicted_regimes: list[str] = []
        actual_regimes: list[str] = []
        forecast_confidences: list[float] = []
        regime_matches: list[bool] = []
        risk_breach_count = 0

        last_index = len(price_list) - forward_horizon
        for index in range(min_history - 1, last_index):
            history_prices = price_list[: index + 1]
            history_volumes = volume_list[: index + 1] if volume_list else None
            forward_prices = price_list[index + 1 : index + 1 + forward_horizon]

            regime_result = self._regime_engine.classify_instrument(
                history_prices,
                history_volumes,
                spread_bps=spread_bps,
                correlation_cluster=correlation_cluster,
            )
            actual_regime = infer_actual_regime_from_forward_prices(
                forward_prices,
                spread_bps=spread_bps,
                correlation_cluster=correlation_cluster,
                regime_engine=self._regime_engine,
            )
            regime_match = regime_result.dominant_regime == actual_regime

            forecast = self._compute_forecast_or_fallback(
                ForecastInputBundle(
                    instrument_id=instrument_id,
                    prices=history_prices,
                    volumes=history_volumes,
                    spread_bps=spread_bps,
                    regime_result=regime_result,
                ),
                regime_result=regime_result,
            )

            history_returns = prices_to_returns(history_prices)
            breached_count = self._assess_risk_breach_count(
                instrument_id=instrument_id,
                history_prices=history_prices,
                history_returns=history_returns,
                budget=budget,
            )
            if breached_count:
                risk_breach_count += 1

            timestamp = timestamp_list[index] if timestamp_list and index < len(timestamp_list) else None
            point = PredictionReplayPoint(
                index=index,
                timestamp=timestamp,
                predicted_regime=regime_result.dominant_regime,
                predicted_regime_confidence=regime_result.confidence,
                actual_regime=actual_regime,
                regime_match=regime_match,
                forecast_confidence=forecast.confidence,
                forecast_composite_risk_score=forecast.composite_risk_score,
                risk_breached_count=breached_count,
                risk_breached=breached_count > 0,
            )
            points.append(point)
            predicted_regimes.append(regime_result.dominant_regime)
            actual_regimes.append(actual_regime)
            forecast_confidences.append(forecast.confidence)
            regime_matches.append(regime_match)

        accuracy = regime_classification_accuracy(predicted_regimes, actual_regimes)
        matrix = build_regime_confusion_matrix(
            predicted_regimes,
            actual_regimes,
            labels=[label.value for label in ALL_REGIME_LABELS],
        )
        calibration_bins_raw, correlation = compute_forecast_calibration(
            forecast_confidences,
            regime_matches,
            bin_count=calibration_bins,
        )
        calibration_bins = tuple(
            ForecastCalibrationBin(
                confidence_min=float(item["confidence_min"]),
                confidence_max=float(item["confidence_max"]),
                count=int(item["count"]),
                accuracy=float(item["accuracy"]),
            )
            for item in calibration_bins_raw
        )

        total_points = len(points)
        return PredictionReplayReport(
            instrument_id=instrument_id,
            total_points=total_points,
            regime_accuracy=accuracy,
            confusion_matrix=RegimeConfusionMatrix(
                labels=tuple(sorted(set(predicted_regimes) | set(actual_regimes))),
                matrix=matrix,
                accuracy=accuracy,
                total=total_points,
            ),
            forecast_calibration=ForecastCalibrationReport(
                bins=calibration_bins,
                confidence_accuracy_correlation=correlation,
            ),
            risk_breach_rate=(risk_breach_count / total_points if total_points else 0.0),
            points=tuple(points),
        )

    def replay_hierarchy(
        self,
        *,
        instrument_id: int,
        prices: Sequence[float],
        volumes: Sequence[float] | None = None,
        sector: str = "technology",
        forward_horizon: int = 10,
        min_history: int = 30,
    ):
        """Forward validation across full prediction hierarchy (Prompts 29/40)."""
        from app.services.prediction_hierarchy.hierarchy_validation import HierarchyValidationEngine

        engine = HierarchyValidationEngine(
            regime_engine=self._regime_engine,
        )
        return engine.run(
            instrument_id=instrument_id,
            prices=prices,
            volumes=volumes,
            sector=sector,
            forward_horizon=forward_horizon,
            min_history=min_history,
        )

    def _compute_forecast_or_fallback(
        self,
        bundle: ForecastInputBundle,
        *,
        regime_result,
    ):
        """Run ForecastEngine; fall back to regime-only map on degenerate return series."""
        try:
            return self._forecast_engine.compute_from_inputs(bundle)
        except ValueError:
            neutral_signals = ForecastSignals(
                short_term_momentum=0.0,
                momentum_direction=ForecastDirection.NEUTRAL,
                tail_risk_score=0.0,
                volatility_expansion_probability=0.0,
                correlation_shift_score=0.0,
                liquidity_deterioration_score=0.0,
                event_impact_score=0.0,
            )
            return aggregate_forecast(
                instrument_id=bundle.instrument_id,
                regime_distribution=dict(regime_result.distribution),
                regime_confidence=regime_result.confidence,
                signals=neutral_signals,
                risk_flag_threshold=self._forecast_engine._settings.FORECAST_RISK_FLAG_THRESHOLD,
                elevated_uncertainty_threshold=(
                    self._forecast_engine._settings.FORECAST_ELEVATED_UNCERTAINTY_THRESHOLD
                ),
            )

    def _assess_risk_breach_count(
        self,
        *,
        instrument_id: int,
        history_prices: list[float],
        history_returns: list[float],
        budget: RiskBudgetContext,
    ) -> int:
        try:
            risk_assessment = self._risk_engine.assess(
                RiskEngineInput(
                    instrument_id=instrument_id,
                    returns_by_instrument={instrument_id: history_returns},
                    prices_by_instrument={instrument_id: history_prices},
                ),
                budget,
            )
        except ValueError:
            return 0
        return len(risk_assessment.breached)

    @staticmethod
    def _context_from_snapshot(snapshot: dict) -> MarketContext:
        return MarketContext(
            instrument_volatility=float(snapshot.get("instrument_volatility", 0.0)),
            instrument_spread_bps=float(snapshot.get("instrument_spread_bps", 0.0)),
            max_correlation_with_portfolio=float(
                snapshot.get("max_correlation_with_portfolio", 0.0)
            ),
            market_regime=str(snapshot.get("market_regime", "unknown")),
            session_killed=bool(snapshot.get("session_killed", False)),
            profile_drawdown_pct=float(snapshot.get("profile_drawdown_pct", 0.0)),
            profile_daily_loss_abs=Decimal(str(snapshot.get("profile_daily_loss_abs", "0"))),
        )

    @staticmethod
    def _risk_snapshot_from_snapshot(snapshot: dict) -> RiskSnapshot:
        return RiskSnapshot(
            profile_drawdown_pct=float(snapshot.get("profile_drawdown_pct", 0.0)),
            profile_daily_loss_abs=Decimal(str(snapshot.get("profile_daily_loss_abs", "0"))),
            sleeve_drawdown_pct=float(snapshot.get("sleeve_drawdown_pct", 0.0)),
            sleeve_daily_loss_abs=Decimal(str(snapshot.get("sleeve_daily_loss_abs", "0"))),
        )
