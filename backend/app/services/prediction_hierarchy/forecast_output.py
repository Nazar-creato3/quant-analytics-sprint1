"""ForecastOutputBuilder — 6-layer unified forecast (Prompt 34)."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

from app.services.control_fabric.risk_types import PortfolioRiskAssessment, RiskEngineInput
from app.services.forecast.distribution import (
    INTERVAL_CONFIDENCE_MULTIPLIER,
    INTERVAL_HORIZON_DAYS,
    WEAK_SIGNAL_THRESHOLD,
    build_forecast_distribution,
)
from app.services.forecast.types import ForecastDirection, InstrumentForecast
from app.services.prediction_hierarchy.marginal_risk import MarginalRiskImpact
from app.services.prediction_hierarchy.scenario_summary import describe_narrative_archetypes
from app.services.prediction_hierarchy.types import (
    ActionForecast,
    DistributionForecast,
    ForecastOutput,
    IntervalForecast,
    PointForecast,
    PointMagnitudeClass,
    RiskForecastLayer,
    RiskItem,
    ScenarioForecast,
    ScenarioForecastItem,
    SectorRegimeContext,
    GlobalRegimeResult,
)
from app.services.quant_math import historical_volatility, rolling_volatility
from app.services.regime.features import prices_to_returns
from app.services.scenario.engine import ScenarioEngine
from app.services.scenario.types import MonteCarloResult, PortfolioSnapshot, ScenarioName, ScenarioResult

_MAGNITUDE_RU: dict[PointMagnitudeClass, str] = {
    PointMagnitudeClass.STRONG_UP: "сильный рост",
    PointMagnitudeClass.UP: "умеренный рост",
    PointMagnitudeClass.NEUTRAL: "боковое движение",
    PointMagnitudeClass.DOWN: "умеренное снижение",
    PointMagnitudeClass.STRONG_DOWN: "сильное снижение",
}

_SCENARIO_RU: dict[str, str] = {
    ScenarioName.RATE_SHOCK.value: "шок процентных ставок",
    ScenarioName.VIX_SPIKE.value: "скачок волатильности (VIX)",
    ScenarioName.CORRELATION_BREAKDOWN.value: "разрыв корреляций",
    ScenarioName.BAD_CPI_SURPRISE.value: "неожиданная инфляция (CPI)",
    ScenarioName.EARNINGS_GAP_DOWN.value: "разочарование отчётностью",
    ScenarioName.SECTOR_LIQUIDITY_DROUGHT.value: "дефицит ликвидности в секторе",
}

_RISK_METRIC_RU: dict[str, str] = {
    "composite_risk_score": "общий риск",
    "tail_risk_score": "хвостовой риск",
    "liquidity_risk_score": "риск ликвидности",
    "volatility_expansion_probability": "вероятность роста волатильности",
    "event_impact_score": "новостной/событийный риск",
    "correlation_shift_score": "сдвиг корреляций",
    "liquidity_deterioration_score": "ухудшение ликвидности",
}


def _magnitude_class(momentum: float, direction: ForecastDirection) -> PointMagnitudeClass:
    if momentum < WEAK_SIGNAL_THRESHOLD or direction == ForecastDirection.NEUTRAL:
        return PointMagnitudeClass.NEUTRAL
    if direction == ForecastDirection.BULLISH:
        return PointMagnitudeClass.STRONG_UP if momentum >= 0.65 else PointMagnitudeClass.UP
    if direction == ForecastDirection.BEARISH:
        return PointMagnitudeClass.STRONG_DOWN if momentum >= 0.65 else PointMagnitudeClass.DOWN
    return PointMagnitudeClass.NEUTRAL


def _return_sign(magnitude: PointMagnitudeClass) -> int:
    if magnitude in {PointMagnitudeClass.STRONG_UP, PointMagnitudeClass.UP}:
        return 1
    if magnitude in {PointMagnitudeClass.STRONG_DOWN, PointMagnitudeClass.DOWN}:
        return -1
    return 0


def _severity(score: float) -> str:
    if score >= 0.70:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _narrative_scenario_probabilities(
    *,
    vol: float,
    momentum: float,
    tail_risk: float,
    composite_risk: float,
    regime_distribution: Mapping[str, float],
) -> dict[str, float]:
    """Mutually exclusive narrative scenario weights — sum to 1.0.

    Semantics (for UI / docs):
    - pessimistic: adverse tail outcome (vol expansion, bearish impulse, stress regimes)
    - realistic: base case aligned with current momentum and dominant regime
    - optimistic: favorable outcome when vol is contained and momentum is positive
    - classic: historical / mean-reversion path (choppy range, neutral drift)
    """
    bearish_pressure = max(0.0, 0.5 - momentum) * 2.0
    bullish_pressure = max(0.0, momentum - 0.5) * 2.0

    choppy = float(regime_distribution.get("choppy_range", 0.0))
    high_vol = float(regime_distribution.get("high_volatility_shock", 0.0))
    bearish_regime = float(regime_distribution.get("bearish_trend", 0.0))
    bullish_regime = float(regime_distribution.get("bullish_trend", 0.0))

    weights = {
        "pessimistic": (
            0.05
            + vol * 0.30
            + tail_risk * 0.25
            + bearish_pressure * 0.20
            + bearish_regime * 0.15
            + high_vol * 0.10
        ),
        "realistic": (
            0.10
            + (1.0 - abs(momentum - 0.5) * 2.0) * 0.25
            + max(bullish_regime, bearish_regime) * 0.20
            + (1.0 - high_vol) * 0.10
            + composite_risk * 0.05
        ),
        "optimistic": (
            0.05
            + (1.0 - vol) * 0.22
            + bullish_pressure * 0.25
            + bullish_regime * 0.20
            + (1.0 - composite_risk) * 0.10
        ),
        "classic": (
            0.05
            + choppy * 0.35
            + (1.0 - abs(bullish_regime - bearish_regime)) * 0.12
            + (1.0 - vol) * 0.10
            + tail_risk * 0.05
        ),
    }
    total = sum(weights.values())
    if total <= 0.0:
        return {key: 0.25 for key in weights}
    return {key: round(value / total, 4) for key, value in weights.items()}


def _dedupe_risk_items(metrics: Mapping[str, float]) -> tuple[RiskItem, ...]:
    """Build deduplicated risk items — merge aliases pointing to same concept."""
    alias_groups: dict[str, tuple[str, ...]] = {
        "liquidity_risk_score": ("liquidity_risk_score", "liquidity_deterioration_score"),
        "tail_risk_score": ("tail_risk_score",),
        "composite_risk_score": ("composite_risk_score",),
        "volatility_expansion_probability": ("volatility_expansion_probability",),
        "event_impact_score": ("event_impact_score",),
        "correlation_shift_score": ("correlation_shift_score",),
    }
    seen: set[str] = set()
    items: list[RiskItem] = []
    for canonical, keys in alias_groups.items():
        if canonical in seen:
            continue
        score = max(float(metrics.get(key, 0.0)) for key in keys)
        if score < 0.30:
            continue
        label = _RISK_METRIC_RU.get(canonical, canonical)
        sev = _severity(score)
        items.append(
            RiskItem(
                metric=canonical,
                score=round(score, 4),
                severity=sev,
                plain_language_summary=(
                    f"{label.capitalize()}: {score:.0%} — "
                    f"{'повышенное внимание' if sev != 'low' else 'в пределах нормы'}"
                ),
            )
        )
        seen.add(canonical)
        for key in keys:
            seen.add(key)
    items.sort(key=lambda item: item.score, reverse=True)
    return tuple(items)


@dataclass(frozen=True, slots=True)
class ForecastSourceBundle:
    """Inputs assembled by orchestrator — builder does not fetch data."""

    instrument_id: int
    symbol: str
    as_of: str
    prices: list[float]
    ticker_forecast: InstrumentForecast
    risk_assessment: PortfolioRiskAssessment | None = None
    marginal_impact: MarginalRiskImpact | None = None
    scenario_results: tuple[ScenarioResult, ...] = ()
    monte_carlo: MonteCarloResult | None = None
    global_regime: GlobalRegimeResult | None = None
    sector_regime: SectorRegimeContext | None = None
    action_forecast: ActionForecast | None = None
    calibrated_confidence: float = 0.0
    narrator_insights: tuple[Any, ...] = ()
    macro_indicators: dict[str, float] = field(default_factory=dict)


class ForecastOutputBuilder:
    """Compose ForecastOutput from existing engine outputs — no new math."""

    def __init__(self, *, scenario_engine: ScenarioEngine | None = None) -> None:
        self._scenario_engine = scenario_engine or ScenarioEngine()

    def build(self, sources: ForecastSourceBundle) -> ForecastOutput:
        point = self._build_point_forecast(
            sources.ticker_forecast,
            sources.symbol,
            sources.prices,
        )
        interval = self._build_interval_forecast(
            sources.prices,
            momentum_score=sources.ticker_forecast.signals.short_term_momentum,
            direction=sources.ticker_forecast.signals.momentum_direction,
        )
        distribution = self._build_distribution_forecast(sources)
        if sources.action_forecast is None:
            raise ValueError("action_forecast must be set before final ForecastOutput assembly")

        scenario = self._build_scenario_forecast(sources, point)
        risk = self._build_risk_forecast(sources)
        confidence = sources.calibrated_confidence or sources.ticker_forecast.confidence

        output = ForecastOutput(
            instrument_id=sources.instrument_id,
            symbol=sources.symbol,
            as_of=sources.as_of,
            point_forecast=point,
            interval_forecast=interval,
            distribution_forecast=distribution,
            scenario_forecast=scenario,
            risk_forecast=risk,
            action_forecast=sources.action_forecast,
            calibrated_confidence=confidence,
            high_confidence=confidence >= 0.85,
            global_regime=sources.global_regime,
            sector_regime=sources.sector_regime,
            narrator_insights=sources.narrator_insights,
            raw_ticker_confidence=sources.ticker_forecast.confidence,
            risk_engine_report=self._build_risk_engine_report(sources, risk),
            prediction_system_report=self._build_prediction_system_report(
                sources,
                confidence,
                scenario,
            ),
        )
        return output

    def _build_point_forecast(
        self,
        forecast: InstrumentForecast,
        symbol: str,
        prices: Sequence[float],
    ) -> PointForecast:
        dist = build_forecast_distribution(
            prices=prices,
            momentum_score=forecast.signals.short_term_momentum,
            direction=forecast.signals.momentum_direction,
        )
        momentum_pct = forecast.signals.short_term_momentum * 100

        # low_confidence is often always-on for single-name UI disclaimers
        # (SINGLE_NAME_DIRECTION_LOW_CONFIDENCE). It must NOT zero the directional
        # call — snapshots/resolutions need expected_return_sign for Wilson eval.
        if dist.insufficient_data:
            return PointForecast(
                magnitude_class=PointMagnitudeClass.NEUTRAL,
                expected_return_sign=0,
                momentum_score=forecast.signals.short_term_momentum,
                plain_language_summary=(
                    f"По {symbol} недостаточно истории для направления "
                    f"({momentum_pct:.0f}% силы). Это не точный прогноз цены."
                ),
            )

        magnitude = _magnitude_class(
            forecast.signals.short_term_momentum,
            forecast.signals.momentum_direction,
        )
        sign = _return_sign(magnitude)
        if sign == 0:
            summary = (
                f"По {symbol} сигнал слабый или симметричный ({momentum_pct:.0f}% силы) — "
                "направление неопределённо. Это не точный прогноз цены."
            )
        else:
            label = _MAGNITUDE_RU.get(magnitude, magnitude.value)
            confidence_note = (
                " Низкая уверенность для одиночного имени — направление оценочное."
                if dist.low_confidence or dist.symmetric_interval
                else ""
            )
            summary = (
                f"По {symbol} краткосрочный импульс указывает на {label} "
                f"(сила сигнала {momentum_pct:.0f}%). Это не точный прогноз цены, "
                f"а оценка направления на основе недавней динамики.{confidence_note}"
            )
        return PointForecast(
            magnitude_class=magnitude,
            expected_return_sign=sign,
            momentum_score=forecast.signals.short_term_momentum,
            plain_language_summary=summary,
        )

    def _build_interval_forecast(
        self,
        prices: Sequence[float],
        *,
        momentum_score: float = 0.5,
        direction: ForecastDirection = ForecastDirection.NEUTRAL,
    ) -> IntervalForecast:
        dist = build_forecast_distribution(
            prices=prices,
            momentum_score=momentum_score,
            direction=direction,
        )
        if dist.insufficient_data:
            return IntervalForecast(
                horizon_days=INTERVAL_HORIZON_DAYS,
                p10=0.0,
                p90=0.0,
                rolling_volatility=0.0,
                confidence_multiplier=INTERVAL_CONFIDENCE_MULTIPLIER,
                plain_language_summary="Недостаточно истории для интервала доходности (insufficient_data).",
            )

        vol = abs(dist.p90 - dist.p10) / (2.0 * INTERVAL_CONFIDENCE_MULTIPLIER)
        vol_pct = vol * 100
        low_note = " (низкая уверенность)" if dist.low_confidence else ""
        summary = (
            f"За {INTERVAL_HORIZON_DAYS} дней диапазон доходности — "
            f"от {dist.p10 * 100:.1f}% до {dist.p90 * 100:.1f}% (90% интервал). "
            f"Текущая историческая волатильность около {vol_pct:.1f}% в день{low_note}."
        )
        return IntervalForecast(
            horizon_days=INTERVAL_HORIZON_DAYS,
            p10=round(dist.p10, 6),
            p90=round(dist.p90, 6),
            rolling_volatility=round(vol, 6),
            confidence_multiplier=INTERVAL_CONFIDENCE_MULTIPLIER,
            plain_language_summary=summary,
        )

    def _build_distribution_forecast(self, sources: ForecastSourceBundle) -> DistributionForecast:
        if sources.monte_carlo is not None:
            bands = sources.monte_carlo.percentile_bands
            summary = (
                f"Модель Монте-Кarlo: медианный сценарий {bands.p50 * 100:.1f}%, "
                f"пессимистичный (5%) {bands.p5 * 100:.1f}%, оптимистичный (95%) {bands.p95 * 100:.1f}%."
            )
            return DistributionForecast(
                p5=bands.p5,
                p25=bands.p25,
                p50=bands.p50,
                p75=bands.p75,
                p95=bands.p95,
                method=(
                    sources.monte_carlo.method.value
                    if hasattr(sources.monte_carlo.method, "value")
                    else str(sources.monte_carlo.method)
                ),
                plain_language_summary=summary,
            )

        returns = prices_to_returns(sources.prices)
        if len(returns) < 5:
            return DistributionForecast(
                p5=0.0,
                p25=0.0,
                p50=0.0,
                p75=0.0,
                p95=0.0,
                method="insufficient_data",
                plain_language_summary="Недостаточно истории для распределения доходностей.",
            )

        sorted_returns = sorted(returns)

        def percentile(values: list[float], pct: float) -> float:
            index = int(pct * (len(values) - 1))
            return round(values[index], 6)

        p5 = percentile(sorted_returns, 0.05)
        p50 = percentile(sorted_returns, 0.50)
        p95 = percentile(sorted_returns, 0.95)
        summary = (
            f"По истории: в 50% дней доходность около {p50 * 100:.2f}%, "
            f"в худшие 5% — до {p5 * 100:.1f}%, в лучшие 5% — до {p95 * 100:.1f}%."
        )
        return DistributionForecast(
            p5=p5,
            p25=percentile(sorted_returns, 0.25),
            p50=p50,
            p75=percentile(sorted_returns, 0.75),
            p95=p95,
            method="historical_percentile",
            plain_language_summary=summary,
        )

    def _build_scenario_forecast(
        self,
        sources: ForecastSourceBundle,
        point: PointForecast,
    ) -> ScenarioForecast:
        stress_items: list[ScenarioForecastItem] = []
        impacts: list[float] = []

        for result in sources.scenario_results:
            name = (
                result.scenario_name.value
                if hasattr(result.scenario_name, "value")
                else str(result.scenario_name)
            )
            prob = min(1.0, abs(result.estimated_pnl_impact) * 3.0 + abs(result.portfolio_variance_delta))
            label = _SCENARIO_RU.get(name, name.replace("_", " "))
            impact_pct = result.estimated_pnl_impact * 100
            stress_items.append(
                ScenarioForecastItem(
                    name=name,
                    probability=round(prob, 4),
                    impact=round(result.estimated_pnl_impact, 6),
                    label_ru=label,
                    scenario_type="stress",
                    impact_narrative_ru=(
                        f"Стресс-сценарий «{label}»: оценочное влияние на портфель {impact_pct:+.1f}%."
                    ),
                )
            )
            impacts.extend([result.estimated_pnl_impact, -result.estimated_pnl_impact])

        signals = sources.ticker_forecast.signals
        vol = signals.volatility_expansion_probability
        momentum = point.momentum_score
        realistic_impact = (momentum - 0.5) * 0.04
        pessimistic_impact = min(-0.02, realistic_impact - vol * 0.06)
        optimistic_impact = max(0.02, realistic_impact + (1 - vol) * 0.05)
        classic_impact = point.momentum_score * 0.02 - 0.01

        from app.services.prediction_hierarchy.scenario_overlay import (
            InstrumentOverlay,
            SectorOverlay,
            build_global_macro_snapshot,
            compute_layered_scenario_probabilities,
        )

        macro_snapshot = None
        if sources.global_regime is not None:
            macro_snapshot = build_global_macro_snapshot(
                indicators=sources.macro_indicators or {"vix": vol * 40.0},
                global_result=sources.global_regime,
                loaded_at=sources.as_of,
            )

        sector_overlay: SectorOverlay | None = None
        if sources.sector_regime is not None:
            sector_ctx = sources.sector_regime
            sector_overlay = SectorOverlay(
                sector=sector_ctx.sector,
                rotation=sector_ctx.rotation,
                sector_momentum=sector_ctx.sector_momentum,
                dominant_sector_regime=sector_ctx.regime.dominant_regime,
                as_of=sources.as_of,
            )

        returns = prices_to_returns(sources.prices) if sources.prices else []
        realized_vol = historical_volatility(returns) if len(returns) >= 2 else 0.0
        instrument_overlay = InstrumentOverlay(
            symbol=sources.symbol,
            momentum=momentum,
            vol_expansion=vol,
            tail_risk=signals.tail_risk_score,
            composite_risk=sources.ticker_forecast.composite_risk_score,
            realized_vol=realized_vol,
            liquidity_score=signals.liquidity_deterioration_score,
            relative_strength=(
                sector_ctx.sector_momentum * 10.0 + (momentum - 0.5)
                if sources.sector_regime
                else momentum - 0.5
            ),
            regime_distribution=sources.ticker_forecast.regime_distribution,
            as_of=sources.as_of,
            expected_move=(momentum - 0.5) * 0.08,
        )

        if macro_snapshot is not None:
            scenario_probs, breakdown, overlay_audit = compute_layered_scenario_probabilities(
                macro=macro_snapshot,
                sector=sector_overlay,
                instrument=instrument_overlay,
                portfolio=None,
            )
        else:
            scenario_probs = _narrative_scenario_probabilities(
                vol=vol,
                momentum=momentum,
                tail_risk=signals.tail_risk_score,
                composite_risk=sources.ticker_forecast.composite_risk_score,
                regime_distribution=sources.ticker_forecast.regime_distribution,
            )
            breakdown = None
            overlay_audit = None

        narrative_scenarios = (
            ScenarioForecastItem(
                name="pessimistic",
                scenario_type="pessimistic",
                label_ru="Пессимистичный",
                probability=scenario_probs["pessimistic"],
                impact=round(pessimistic_impact, 6),
                impact_narrative_ru=(
                    f"Пессимистичный сценарий: рост волатильности и негативный импульс "
                    f"могут дать просадку порядка {pessimistic_impact * 100:.1f}%."
                ),
            ),
            ScenarioForecastItem(
                name="realistic",
                scenario_type="realistic",
                label_ru="Реалистичный",
                probability=scenario_probs["realistic"],
                impact=round(realistic_impact, 6),
                impact_narrative_ru=(
                    f"Базовый сценарий: {_MAGNITUDE_RU.get(point.magnitude_class, 'нейтраль')} "
                    f"с ожидаемым эффектом около {realistic_impact * 100:+.1f}%."
                ),
            ),
            ScenarioForecastItem(
                name="optimistic",
                scenario_type="optimistic",
                label_ru="Оптимистичный",
                probability=scenario_probs["optimistic"],
                impact=round(optimistic_impact, 6),
                impact_narrative_ru=(
                    f"Оптимистичный сценарий: при спокойном рынке возможен рост "
                    f"до {optimistic_impact * 100:+.1f}%."
                ),
            ),
            ScenarioForecastItem(
                name="classic",
                scenario_type="classic",
                label_ru="Классический (исторический)",
                probability=scenario_probs["classic"],
                impact=round(classic_impact, 6),
                impact_narrative_ru=(
                    f"Классический сценарий по историческим паттернам: "
                    f"типичный исход около {classic_impact * 100:+.1f}%."
                ),
            ),
        )

        if not stress_items and sources.prices:
            returns = prices_to_returns(sources.prices)
            vol_series = rolling_volatility(returns, window=min(10, len(returns)))
            if vol_series:
                dispersion = max(vol_series) - min(vol_series)
                stress_items.append(
                    ScenarioForecastItem(
                        name="volatility_range",
                        probability=0.5,
                        impact=round(dispersion, 6),
                        label_ru="Диапазон волатильности",
                        scenario_type="stress",
                        impact_narrative_ru=f"Размах волатильности за период: {dispersion * 100:.1f}%.",
                    )
                )
                impacts = [dispersion, -dispersion]

        all_items = tuple(narrative_scenarios) + tuple(stress_items)
        dispersion = max(impacts) - min(impacts) if len(impacts) >= 2 else abs(classic_impact) * 2
        overlay_breakdown = breakdown.to_dict() if breakdown is not None else {}
        return ScenarioForecast(
            scenarios=all_items,
            scenario_dispersion=round(abs(dispersion), 6),
            overlay_breakdown=overlay_breakdown,
            overlay_audit=overlay_audit or {},
        )

    def _build_risk_forecast(self, sources: ForecastSourceBundle) -> RiskForecastLayer:
        instrument_metrics: dict[str, float] = {
            "composite_risk_score": sources.ticker_forecast.composite_risk_score,
            "tail_risk_score": sources.ticker_forecast.signals.tail_risk_score,
            "liquidity_risk_score": sources.ticker_forecast.signals.liquidity_deterioration_score,
            "volatility_expansion_probability": sources.ticker_forecast.signals.volatility_expansion_probability,
            "event_impact_score": sources.ticker_forecast.signals.event_impact_score,
            "correlation_shift_score": sources.ticker_forecast.signals.correlation_shift_score,
        }
        portfolio_metrics: dict[str, float] = {}
        breached: list[str] = []

        if sources.risk_assessment is not None:
            for metric in sources.risk_assessment.metrics:
                key = f"{metric.scope}_{metric.name}"
                portfolio_metrics[key] = metric.value
                if metric.exceeded and metric.name not in breached:
                    breached.append(metric.name)
            for assessment in sources.risk_assessment.instrument_assessments:
                if assessment.instrument_id == sources.instrument_id:
                    for metric in assessment.metrics:
                        instrument_metrics[metric.name] = metric.value
                        if metric.exceeded and metric.name not in breached:
                            breached.append(metric.name)

        risk_items = _dedupe_risk_items(instrument_metrics)
        composite = instrument_metrics.get("composite_risk_score", 0.0)
        top_risks = ", ".join(item.plain_language_summary.split(":")[0] for item in risk_items[:3])
        summary = (
            f"Общий риск по {sources.symbol}: {composite:.0%}. "
            f"{'Ключевые факторы: ' + top_risks + '.' if top_risks else 'Существенных рисков не выявлено.'}"
        )

        return RiskForecastLayer(
            instrument_metrics=instrument_metrics,
            portfolio_metrics=portfolio_metrics,
            marginal_impact=sources.marginal_impact,
            breached_metrics=tuple(breached),
            plain_language_summary=summary,
            risk_items=risk_items,
        )

    def _build_risk_engine_report(
        self,
        sources: ForecastSourceBundle,
        risk: RiskForecastLayer,
    ) -> dict[str, Any]:
        report: dict[str, Any] = {
            "engine": "RiskEngine",
            "instrument_id": sources.instrument_id,
            "symbol": sources.symbol,
            "composite_risk_score": risk.instrument_metrics.get("composite_risk_score", 0.0),
            "breached_metrics": list(risk.breached_metrics),
            "risk_items_count": len(risk.risk_items),
            "input_signals": sources.ticker_forecast.signals.as_dict(),
        }
        if sources.risk_assessment is not None:
            report["portfolio_metrics"] = {
                metric.name: {
                    "value": metric.value,
                    "threshold": metric.threshold,
                    "exceeded": metric.exceeded,
                    "scope": metric.scope,
                }
                for metric in sources.risk_assessment.metrics
            }
        if sources.marginal_impact is not None:
            report["marginal_impact"] = {
                "delta_var": sources.marginal_impact.delta_var,
                "delta_es": sources.marginal_impact.delta_es,
                "new_correlation_cluster_exposure": sources.marginal_impact.new_correlation_cluster_exposure,
            }
        return report

    def _build_prediction_system_report(
        self,
        sources: ForecastSourceBundle,
        confidence: float,
        scenario: ScenarioForecast,
    ) -> dict[str, Any]:
        engines = ["GlobalMacroRegimeEngine", "SectorRegimeEngine", "RegimeEngine", "ForecastEngine"]
        if sources.risk_assessment is not None:
            engines.append("RiskEngine")
        if sources.scenario_results:
            engines.append("ScenarioEngine")
        engines.extend(["ActionForecastEngine", "ForecastConfidenceCalibrator"])

        narrative_items = [
            (
                item.scenario_type or item.name,
                item.label_ru,
                item.probability,
                item.impact,
            )
            for item in scenario.scenarios
            if (item.scenario_type or item.name)
            in {"pessimistic", "realistic", "optimistic", "classic"}
        ]
        general_summary = describe_narrative_archetypes(
            narrative_items,
            symbol=sources.symbol,
        )

        return {
            "engines_used": engines,
            "calibrated_confidence": confidence,
            "raw_ticker_confidence": sources.ticker_forecast.confidence,
            "scenario_count": len(sources.scenario_results),
            "general_summary": general_summary,
            "global_regime": (
                {
                    "dominant_regime": sources.global_regime.dominant_regime,
                    "confidence": sources.global_regime.confidence,
                    "distribution_top3": sorted(
                        sources.global_regime.distribution.items(),
                        key=lambda item: item[1],
                        reverse=True,
                    )[:3],
                }
                if sources.global_regime
                else None
            ),
            "sector_regime": (
                {
                    "sector": sources.sector_regime.sector,
                    "rotation_flag": sources.sector_regime.rotation.rotation_flag.value,
                    "composite_score": sources.sector_regime.rotation.composite_score,
                }
                if sources.sector_regime
                else None
            ),
            "price_history_bars": len(sources.prices),
        }

    def run_default_scenarios(
        self,
        portfolio: PortfolioSnapshot,
    ) -> tuple[ScenarioResult, ...]:
        results: list[ScenarioResult] = []
        for scenario in (
            ScenarioName.RATE_SHOCK,
            ScenarioName.VIX_SPIKE,
            ScenarioName.CORRELATION_BREAKDOWN,
        ):
            try:
                results.append(self._scenario_engine.run(scenario, portfolio))
            except (ValueError, KeyError):
                continue
        return tuple(results)

    @staticmethod
    def apply_explainability(
        output: ForecastOutput,
        *,
        instruction_block: str,
        basis_block: tuple[Any, ...],
    ) -> ForecastOutput:
        return replace(
            output,
            instruction_block=instruction_block,
            basis_block=basis_block,
        )
