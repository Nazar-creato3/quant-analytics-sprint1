"""ActionForecastEngine — rule-based advisory recommendations (Prompt 35)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.services.prediction_hierarchy.types import (
    ActionForecast,
    ActionRecommendation,
    ForecastOutput,
    GlobalRegimeResult,
    SectorRegimeContext,
    SectorRotationFlag,
)


@dataclass(frozen=True, slots=True)
class ActionForecastContext:
    """Context for rule evaluation without action_forecast field."""

    calibrated_confidence: float
    composite_risk_score: float
    scenario_dispersion: float
    global_regime: GlobalRegimeResult | None = None
    sector_regime: SectorRegimeContext | None = None
    liquidity_score: float = 1.0
    marginal_delta_var: float = 0.0
    remaining_risk_budget_var: float | None = None
    active_locks: frozenset[str] = frozenset()
    tail_risk_score: float = 0.0
    volatility_expansion_probability: float = 0.0


class ActionForecastEngine:
    """Deterministic rule-based translator — advisory only, no DealIntent creation."""

    def evaluate(self, context: ActionForecastContext) -> ActionForecast:
        """Apply explicit rules in priority order."""
        rules: list[tuple[str, ActionForecast]] = [
            self._rule_active_locks(context),
            self._rule_liquidity_drought(context),
            self._rule_marginal_risk_budget(context),
            self._rule_global_uncertainty(context),
            self._rule_high_dispersion(context),
            self._rule_sector_weakness(context),
            self._rule_tail_risk(context),
            self._rule_favorable_entry(context),
            self._rule_hold(context),
        ]
        for rule_id, forecast in rules:
            if forecast is not None:
                return ActionForecast(
                    recommendation=forecast.recommendation,
                    reason=forecast.reason,
                    rule_id=rule_id,
                )
        return ActionForecast(
            recommendation=ActionRecommendation.WAIT,
            reason="No decisive rule matched; default to wait for clearer signals",
            rule_id="default_wait",
        )

    def evaluate_from_output(
        self,
        output: ForecastOutput,
        *,
        liquidity_score: float = 1.0,
        active_locks: Sequence[str] = (),
        remaining_risk_budget_var: float | None = None,
    ) -> ActionForecast:
        marginal_delta = 0.0
        if output.risk_forecast.marginal_impact:
            marginal_delta = output.risk_forecast.marginal_impact.delta_var

        context = ActionForecastContext(
            calibrated_confidence=output.calibrated_confidence,
            composite_risk_score=output.risk_forecast.instrument_metrics.get(
                "composite_risk_score", 0.0
            ),
            scenario_dispersion=output.scenario_forecast.scenario_dispersion,
            global_regime=output.global_regime,
            sector_regime=output.sector_regime,
            liquidity_score=liquidity_score,
            marginal_delta_var=marginal_delta,
            remaining_risk_budget_var=remaining_risk_budget_var,
            active_locks=frozenset(active_locks),
            tail_risk_score=output.risk_forecast.instrument_metrics.get("tail_risk_score", 0.0),
            volatility_expansion_probability=output.risk_forecast.instrument_metrics.get(
                "volatility_expansion_probability", 0.0
            ),
        )
        return self.evaluate(context)

    @staticmethod
    def _rule_active_locks(context: ActionForecastContext) -> tuple[str, ActionForecast | None]:
        if "news_lock" in context.active_locks or "liquidity_drought" in context.active_locks:
            locks = ", ".join(sorted(context.active_locks))
            return (
                "active_locks",
                ActionForecast(
                    recommendation=ActionRecommendation.AVOID,
                    reason=f"Active locks block entry: {locks}",
                    rule_id="active_locks",
                ),
            )
        return ("active_locks", None)

    @staticmethod
    def _rule_liquidity_drought(context: ActionForecastContext) -> tuple[str, ActionForecast | None]:
        if context.liquidity_score < 0.35:
            return (
                "liquidity_drought",
                ActionForecast(
                    recommendation=ActionRecommendation.WAIT,
                    reason=(
                        f"Liquidity score {context.liquidity_score:.2f} below safe threshold 0.35; "
                        "defer entry until depth recovers"
                    ),
                    rule_id="liquidity_drought",
                ),
            )
        return ("liquidity_drought", None)

    @staticmethod
    def _rule_marginal_risk_budget(context: ActionForecastContext) -> tuple[str, ActionForecast | None]:
        budget = context.remaining_risk_budget_var
        if budget is not None and context.marginal_delta_var > budget:
            return (
                "marginal_risk_budget",
                ActionForecast(
                    recommendation=ActionRecommendation.REDUCE_SIZE,
                    reason=(
                        f"Proposed position delta_var {context.marginal_delta_var:.4f} exceeds "
                        f"remaining risk budget {budget:.4f}"
                    ),
                    rule_id="marginal_risk_budget",
                ),
            )
        return ("marginal_risk_budget", None)

    @staticmethod
    def _rule_global_uncertainty(context: ActionForecastContext) -> tuple[str, ActionForecast | None]:
        global_regime = context.global_regime
        if global_regime is None:
            return ("global_uncertainty", None)
        if global_regime.dominant_regime in {"macro_uncertainty", "credit_stress"}:
            if global_regime.confidence < 0.5 or global_regime.confidence_damping_active:
                return (
                    "global_uncertainty",
                    ActionForecast(
                        recommendation=ActionRecommendation.WAIT,
                        reason=(
                            f"Global regime {global_regime.dominant_regime} with confidence "
                            f"{global_regime.confidence:.2f} — macro context unstable"
                        ),
                        rule_id="global_uncertainty",
                    ),
                )
        return ("global_uncertainty", None)

    @staticmethod
    def _rule_high_dispersion(context: ActionForecastContext) -> tuple[str, ActionForecast | None]:
        if context.scenario_dispersion >= 0.08:
            return (
                "high_dispersion",
                ActionForecast(
                    recommendation=ActionRecommendation.HEDGE,
                    reason=(
                        f"Scenario dispersion {context.scenario_dispersion:.4f} indicates "
                        "wide outcome range — consider hedging"
                    ),
                    rule_id="high_dispersion",
                ),
            )
        return ("high_dispersion", None)

    @staticmethod
    def _rule_sector_weakness(context: ActionForecastContext) -> tuple[str, ActionForecast | None]:
        sector = context.sector_regime
        if sector and sector.rotation.rotation_flag == SectorRotationFlag.SECTORS_WEAKENING:
            return (
                "sector_weakness",
                ActionForecast(
                    recommendation=ActionRecommendation.ENTER_SMALL_SIZE,
                    reason=(
                        f"Sector {sector.sector} weakening (rotation score "
                        f"{sector.rotation.composite_score:.4f}) — small size only if entering"
                    ),
                    rule_id="sector_weakness",
                ),
            )
        return ("sector_weakness", None)

    @staticmethod
    def _rule_tail_risk(context: ActionForecastContext) -> tuple[str, ActionForecast | None]:
        if context.tail_risk_score >= 0.65 or context.composite_risk_score >= 0.70:
            return (
                "tail_risk",
                ActionForecast(
                    recommendation=ActionRecommendation.REDUCE_SIZE,
                    reason=(
                        f"Elevated tail/composite risk "
                        f"(tail={context.tail_risk_score:.2f}, composite={context.composite_risk_score:.2f})"
                    ),
                    rule_id="tail_risk",
                ),
            )
        return ("tail_risk", None)

    @staticmethod
    def _rule_favorable_entry(context: ActionForecastContext) -> tuple[str, ActionForecast | None]:
        if (
            context.calibrated_confidence >= 0.70
            and context.composite_risk_score <= 0.40
            and context.liquidity_score >= 0.60
        ):
            rec = (
                ActionRecommendation.ENTER_NORMAL_SIZE
                if context.calibrated_confidence >= 0.85
                else ActionRecommendation.ENTER_SMALL_SIZE
            )
            return (
                "favorable_entry",
                ActionForecast(
                    recommendation=rec,
                    reason=(
                        f"Confidence {context.calibrated_confidence:.2f}, composite risk "
                        f"{context.composite_risk_score:.2f}, liquidity {context.liquidity_score:.2f}"
                    ),
                    rule_id="favorable_entry",
                ),
            )
        return ("favorable_entry", None)

    @staticmethod
    def _rule_hold(context: ActionForecastContext) -> tuple[str, ActionForecast | None]:
        if context.composite_risk_score <= 0.50 and context.calibrated_confidence >= 0.55:
            return (
                "hold",
                ActionForecast(
                    recommendation=ActionRecommendation.HOLD,
                    reason=(
                        f"Moderate risk ({context.composite_risk_score:.2f}) with adequate "
                        f"confidence ({context.calibrated_confidence:.2f}) — maintain current stance"
                    ),
                    rule_id="hold",
                ),
            )
        return ("hold", None)
