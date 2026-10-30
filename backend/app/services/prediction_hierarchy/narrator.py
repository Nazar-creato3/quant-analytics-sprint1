"""PredictionNarrator — plain-language forecast insights (Prompt 36)."""
from __future__ import annotations

from typing import Mapping, Sequence

from app.services.forecast.types import InstrumentForecast
from app.services.prediction_hierarchy.interval_support import interval_band_is_supported
from app.services.prediction_hierarchy.types import (
    ActionRecommendation,
    BasisLayerBlock,
    ForecastOutput,
    HIGH_CONFIDENCE_THRESHOLD,
    NarratorInsight,
)

_ACTION_RU: dict[ActionRecommendation, str] = {
    ActionRecommendation.WAIT: "Подождите — дождитесь более ясных сигналов перед действием.",
    ActionRecommendation.REDUCE_SIZE: "Сократите размер позиции — риск выше комфортного уровня.",
    ActionRecommendation.HEDGE: "Рассмотрите хеджирование — возможен широкий диапазон исходов.",
    ActionRecommendation.HOLD: "Держите текущую позицию — риск и уверенность в балансе.",
    ActionRecommendation.ENTER_SMALL_SIZE: "Можно войти маленьким объёмом — условия умеренно благоприятны.",
    ActionRecommendation.ENTER_NORMAL_SIZE: "Можно войти обычным объёмом — сигналы достаточно сильные.",
    ActionRecommendation.AVOID: "Избегайте входа — активные ограничения или высокий риск.",
}


class PredictionNarrator:
    """Generate 'what it means' insight phrases with mandatory numeric substitution."""

    def narrate(
        self,
        output: ForecastOutput,
        *,
        news_impact_probability: float = 0.0,
        factor_exposures: Mapping[str, float] | None = None,
        correlation_cluster_pct: float = 0.0,
        language: str = "ru",
    ) -> tuple[NarratorInsight, ...]:
        insights: list[NarratorInsight] = []
        factors = factor_exposures or {}

        if output.global_regime and output.global_regime.confidence < 0.55:
            conf = output.global_regime.confidence
            insights.append(
                NarratorInsight(
                    template_id="global_unstable",
                    text_ru=f"Рынок сейчас в нестабильном режиме (уверенность макро-контекста {conf:.0%})",
                    text_en=f"Market is in an unstable macro regime (global confidence {conf:.0%})",
                    source_metric="global_regime.confidence",
                    source_value=conf,
                )
            )

        if output.sector_regime:
            sr = output.sector_regime
            flag = sr.rotation.rotation_flag.value.replace("_", " ")
            if sr.rotation.composite_score >= 0.15 or sr.sector_momentum >= 0.05:
                insights.append(
                    NarratorInsight(
                        template_id="sector_rotation",
                        text_ru=(
                            f"Сектор {sr.sector}: ротация {flag}, "
                            f"импульс {sr.sector_momentum:+.2f}, "
                            f"оценка {sr.rotation.composite_score:.3f}"
                        ),
                        text_en=(
                            f"Sector {sr.sector}: rotation {flag}, "
                            f"momentum {sr.sector_momentum:+.2f}"
                        ),
                        source_metric="sector_regime.composite_score",
                        source_value=sr.rotation.composite_score,
                    )
                )

        if news_impact_probability >= 0.45:
            insights.append(
                NarratorInsight(
                    template_id="news_sensitive",
                    text_ru=(
                        f"Этот тикер чувствителен к новостям "
                        f"(вероятность импакта {news_impact_probability:.0%})"
                    ),
                    text_en=(
                        f"This ticker is news-sensitive "
                        f"(impact probability {news_impact_probability:.0%})"
                    ),
                    source_metric="news_impact_probability",
                    source_value=news_impact_probability,
                )
            )

        if factors:
            dominant = max(factors.items(), key=lambda item: abs(item[1]))
            total_abs = sum(abs(value) for value in factors.values()) or 1.0
            share = abs(dominant[1]) / total_abs
            if share >= 0.45:
                insights.append(
                    NarratorInsight(
                        template_id="factor_concentration",
                        text_ru=(
                            f"Риск перегружен фактором {dominant[0]} "
                            f"(β={dominant[1]:+.2f}, доля {share:.0%})"
                        ),
                        text_en=(
                            f"Risk is concentrated in factor {dominant[0]} "
                            f"(β={dominant[1]:+.2f}, share {share:.0%})"
                        ),
                        source_metric=f"factor_exposure.{dominant[0]}",
                        source_value=dominant[1],
                    )
                )

        action = output.action_forecast.recommendation
        if action == ActionRecommendation.ENTER_SMALL_SIZE:
            insights.append(
                NarratorInsight(
                    template_id="small_size_only",
                    text_ru=(
                        f"Позиция безопасна только при маленьком размере "
                        f"(рекомендация: {action.value})"
                    ),
                    text_en=f"Position is safe only at small size (recommendation: {action.value})",
                    source_metric="action_forecast.recommendation",
                    source_value=1.0,
                )
            )

        if "liquidity_drought" in (output.metadata.get("active_locks") or []):
            liq = output.metadata.get("liquidity_score", 0.0)
            insights.append(
                NarratorInsight(
                    template_id="liquidity_defer",
                    text_ru=(
                        f"Вход лучше отложить до стабилизации ликвидности "
                        f"(liquidity_score={float(liq):.2f})"
                    ),
                    text_en=(
                        f"Defer entry until liquidity stabilizes "
                        f"(liquidity_score={float(liq):.2f})"
                    ),
                    source_metric="liquidity_score",
                    source_value=float(liq),
                )
            )

        if correlation_cluster_pct >= 25.0:
            insights.append(
                NarratorInsight(
                    template_id="correlation_cluster",
                    text_ru=(
                        f"Портфель уже слишком коррелирован "
                        f"(кластер {correlation_cluster_pct:.1f}% капитала)"
                    ),
                    text_en=(
                        f"Portfolio is overly correlated "
                        f"(cluster {correlation_cluster_pct:.1f}% of capital)"
                    ),
                    source_metric="correlation_cluster_pct",
                    source_value=correlation_cluster_pct,
                )
            )

        vol_exp = output.risk_forecast.instrument_metrics.get(
            "volatility_expansion_probability",
            output.metadata.get("volatility_expansion_probability", 0.0),
        )
        if float(vol_exp) >= 0.50:
            insights.append(
                NarratorInsight(
                    template_id="vol_expansion",
                    text_ru=(
                        f"В ближайшие дни высок шанс расширения волатильности "
                        f"({float(vol_exp):.0%})"
                    ),
                    text_en=(
                        f"High probability of volatility expansion in coming days "
                        f"({float(vol_exp):.0%})"
                    ),
                    source_metric="volatility_expansion_probability",
                    source_value=float(vol_exp),
                )
            )

        interval = output.interval_forecast
        band_width = abs(interval.p90 - interval.p10)
        if interval_band_is_supported(
            interval,
            distribution=output.distribution_forecast,
            metadata=output.metadata,
        ):
            insights.append(
                NarratorInsight(
                    template_id="wide_interval",
                    text_ru=(
                        f"Диапазон исходов широкий (P10…P90 ≈ {interval.p10:+.1%}…{interval.p90:+.1%}) — "
                        f"горизонт {interval.horizon_days}д"
                    ),
                    text_en=(
                        f"Outcome band is wide (P10…P90 ≈ {interval.p10:+.1%}…{interval.p90:+.1%}) — "
                        f"{interval.horizon_days}d horizon"
                    ),
                    source_metric="interval_forecast.band_width",
                    source_value=band_width,
                )
            )

        conf = output.calibrated_confidence
        if conf < 0.45:
            insights.append(
                NarratorInsight(
                    template_id="low_confidence",
                    text_ru=(
                        f"Уверенность системы ниже средней ({conf:.0%}) — "
                        "лучше дождаться подтверждения сигналов"
                    ),
                    text_en=(
                        f"System confidence is below average ({conf:.0%}) — "
                        "wait for signal confirmation"
                    ),
                    source_metric="calibrated_confidence",
                    source_value=conf,
                )
            )
        elif conf >= HIGH_CONFIDENCE_THRESHOLD:
            insights.append(
                NarratorInsight(
                    template_id="high_confidence",
                    text_ru=(
                        f"Сигналы согласованы между слоями модели (уверенность {conf:.0%})"
                    ),
                    text_en=f"Signals are aligned across model layers (confidence {conf:.0%})",
                    source_metric="calibrated_confidence",
                    source_value=conf,
                )
            )

        if language == "en":
            return tuple(
                NarratorInsight(
                    template_id=i.template_id,
                    text_ru=i.text_ru,
                    text_en=i.text_en,
                    source_metric=i.source_metric,
                    source_value=i.source_value,
                )
                for i in insights
            )
        return tuple(insights)

    def build_instruction_block(
        self,
        output: ForecastOutput,
        insights: Sequence[NarratorInsight],
    ) -> str:
        """Plain-language 'what to do' from ActionForecastEngine + narrator."""
        action = output.action_forecast.recommendation
        base = _ACTION_RU.get(action, f"Рекомендация: {action.value}.")
        reason = output.action_forecast.reason
        parts = [f"Что делать по {output.symbol}: {base}", f"Обоснование правила: {reason}."]
        if insights:
            context = "; ".join(item.text_ru for item in insights[:3])
            parts.append(f"Контекст: {context}.")
        parts.append(
            f"Итоговая уверенность системы: {output.calibrated_confidence:.0%}."
        )
        return " ".join(parts)

    def build_basis_block(
        self,
        output: ForecastOutput,
        *,
        ticker_forecast: InstrumentForecast | None = None,
    ) -> tuple[BasisLayerBlock, ...]:
        """Per-layer source engine, input metrics, conclusion in RU."""
        blocks: list[BasisLayerBlock] = []

        signals = ticker_forecast.signals if ticker_forecast else None
        point = output.point_forecast
        blocks.append(
            BasisLayerBlock(
                layer="point",
                engine="ForecastEngine",
                input_metrics={
                    "momentum_score": point.momentum_score,
                    **(signals.as_dict() if signals else {}),
                },
                conclusion_ru=point.plain_language_summary or (
                    f"Точечный прогноз: импульс {point.momentum_score:.0%}."
                ),
            )
        )

        interval = output.interval_forecast
        blocks.append(
            BasisLayerBlock(
                layer="interval",
                engine="ForecastOutputBuilder",
                input_metrics={
                    "horizon_days": float(interval.horizon_days),
                    "p10": interval.p10,
                    "p90": interval.p90,
                    "rolling_volatility": interval.rolling_volatility,
                },
                conclusion_ru=interval.plain_language_summary,
            )
        )

        dist = output.distribution_forecast
        blocks.append(
            BasisLayerBlock(
                layer="distribution",
                engine="ForecastOutputBuilder",
                input_metrics={
                    "p5": dist.p5,
                    "p50": dist.p50,
                    "p95": dist.p95,
                    "method": 1.0 if dist.method != "insufficient_data" else 0.0,
                },
                conclusion_ru=dist.plain_language_summary,
            )
        )

        scenario_types = {
            item.scenario_type: item.probability
            for item in output.scenario_forecast.scenarios
            if item.scenario_type in {"pessimistic", "realistic", "optimistic", "classic"}
        }
        blocks.append(
            BasisLayerBlock(
                layer="scenario",
                engine="ScenarioEngine",
                input_metrics=scenario_types or {"scenario_dispersion": output.scenario_forecast.scenario_dispersion},
                conclusion_ru=(
                    "Сценарии: "
                    + ", ".join(
                        f"{name} ({prob:.0%})"
                        for name, prob in sorted(scenario_types.items(), key=lambda x: -x[1])
                    )
                    if scenario_types
                    else f"Дисперсия сценариев {output.scenario_forecast.scenario_dispersion:.4f}."
                ),
            )
        )

        risk = output.risk_forecast
        blocks.append(
            BasisLayerBlock(
                layer="risk",
                engine="RiskEngine",
                input_metrics={
                    key: value
                    for key, value in risk.instrument_metrics.items()
                    if isinstance(value, (int, float))
                },
                conclusion_ru=risk.plain_language_summary,
            )
        )

        if output.global_regime:
            blocks.append(
                BasisLayerBlock(
                    layer="global_regime",
                    engine="GlobalMacroRegimeEngine",
                    input_metrics={
                        "confidence": output.global_regime.confidence,
                        **{
                            f"prob_{k}": v
                            for k, v in list(output.global_regime.distribution.items())[:5]
                        },
                    },
                    conclusion_ru=(
                        f"Глобальный режим: {output.global_regime.dominant_regime} "
                        f"(уверенность {output.global_regime.confidence:.0%})."
                    ),
                )
            )

        if output.sector_regime:
            blocks.append(
                BasisLayerBlock(
                    layer="sector_regime",
                    engine="SectorRegimeEngine",
                    input_metrics={
                        "composite_score": output.sector_regime.rotation.composite_score,
                        "sector_momentum": output.sector_regime.sector_momentum,
                    },
                    conclusion_ru=(
                        f"Сектор {output.sector_regime.sector}: "
                        f"ротация {output.sector_regime.rotation.rotation_flag.value}, "
                        f"оценка {output.sector_regime.rotation.composite_score:.4f}."
                    ),
                )
            )

        blocks.append(
            BasisLayerBlock(
                layer="action",
                engine="ActionForecastEngine",
                input_metrics={
                    "calibrated_confidence": output.calibrated_confidence,
                    "composite_risk_score": risk.instrument_metrics.get("composite_risk_score", 0.0),
                },
                conclusion_ru=(
                    f"Действие: {output.action_forecast.recommendation.value}. "
                    f"{output.action_forecast.reason}"
                ),
            )
        )

        return tuple(blocks)

    def primary_text(self, insights: Sequence[NarratorInsight], *, language: str = "ru") -> list[str]:
        if language == "en":
            return [item.text_en for item in insights]
        return [item.text_ru for item in insights]

    def narrate_macro_level_change(
        self,
        label: str,
        *,
        prior: float | None,
        current: float,
        unit: str,
    ) -> str:
        """WoW / macro diff phrasing reused by MacroReportEngine (Prompt 50)."""
        if prior is None:
            return f"{label}: текущее значение {current}{unit} (недостаточно истории для сравнения)."
        delta = round(current - prior, 4)
        if delta == 0:
            direction = "без изменений"
        elif delta > 0:
            direction = "рост"
        else:
            direction = "снижение"
        return (
            f"{label}: {prior}{unit} → {current}{unit} "
            f"({direction}, Δ{delta}{unit})."
        )
