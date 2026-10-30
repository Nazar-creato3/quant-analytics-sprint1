"""Data-driven disclosure of scenario archetypes — four overlay layers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from app.services.prediction_hierarchy.forecast_output import _narrative_scenario_probabilities
from app.services.prediction_hierarchy.scenario_overlay import (
    ForecastOverlayBundle,
    GlobalMacroSnapshot,
    InstrumentOverlay,
    PortfolioOverlay,
    SectorOverlay,
    build_forecast_overlays,
    build_global_macro_snapshot,
    translate_global_regime,
    translate_risk_action,
    translate_rotation_flag,
    translate_sector_name,
    translate_sector_regime,
    translate_volatility_regime,
)
from app.services.prediction_hierarchy.scenario_summary import CLOSE_SCENARIO_THRESHOLD
from app.services.prediction_hierarchy.types import (
    ForecastOutput,
    GlobalRegimeResult,
    ScenarioForecast,
    SectorRotationFlag,
    SectorRotationScore,
)

_ARCHETYPE_RU: dict[str, str] = {
    "pessimistic": "пессимистичный",
    "realistic": "реалистичный",
    "optimistic": "оптимистичный",
    "classic": "классический (исторический)",
}

_ARCHETYPE_KEYS = ("pessimistic", "realistic", "optimistic", "classic")

_ARCHETYPE_IMPLICATIONS: dict[str, str] = {
    "pessimistic": (
        "обычно усиливается волатильность, рисковые активы испытывают давление, "
        "ликвидность сужается — разумно сократить риск и дождаться стабилизации фона"
    ),
    "realistic": (
        "базовый сценарий предполагает следование текущему импульсу и доминирующему "
        "макро-режиму — умеренное позиционирование с контролем редких, но сильных просадок"
    ),
    "optimistic": (
        "сжатие волатильности и позитивный импульс поддерживают приток в рисковые активы — "
        "фокус на лидирующих секторах при сохранении дисциплины по стопам"
    ),
    "classic": (
        "исторический путь — боковик с ограниченным дрейфом и возвратом к среднему — "
        "торговля в диапазоне и секторная селективность вместо агрессивных направленных ставок"
    ),
}


def _pct(probability: float) -> str:
    return f"{round(max(0.0, min(1.0, probability)) * 100.0, 1)}%"


def _pct_plain(probability: float) -> str:
    value = round(max(0.0, min(1.0, probability)) * 100.0, 1)
    if value == int(value):
        return f"около {int(value)}%"
    return f"около {value}%"


def _sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    if text[0].islower():
        text = text[0].upper() + text[1:]
    if not text.endswith("."):
        text += "."
    return text


def _impact_phrase(impact: float | None) -> str:
    if impact is None:
        return ""
    move = impact * 100.0
    if abs(move) < 0.3:
        return "ожидается практически неизменный уровень цены"
    direction = "рост" if move > 0 else "снижение"
    return f"ожидается {direction} порядка {abs(move):.1f}%"


def _momentum_phrase(momentum: float) -> str:
    if momentum > 0.6:
        return "импульс заметно положительный"
    if momentum < 0.4:
        return "импульс слабый или отрицательный"
    return "импульс нейтральный"


def _tail_risk_phrase(tail_risk: float) -> str:
    if tail_risk >= 0.6:
        return "хвостовой риск высокий"
    if tail_risk >= 0.35:
        return "хвостовой риск умеренно повышен"
    return "хвостовой риск умеренный"


def _liquidity_phrase(liquidity_score: float) -> str:
    quality = 1.0 - liquidity_score
    if quality >= 0.7:
        return "ликвидность достаточная"
    if quality >= 0.45:
        return "ликвидность удовлетворительная"
    return "ликвидность ограничена"


def _score_pct(value: float) -> str:
    return f"{max(0.0, min(1.0, value)) * 100.0:.0f}%"


def _compact_regime_ru(regime: str) -> str:
    return translate_global_regime(regime).replace(" (risk-on)", "").replace(" (risk-off)", "")


@dataclass(frozen=True, slots=True)
class ScenarioDisclosureResult:
    """Structured scenario archetype disclosure for API responses."""

    paragraphs: tuple[str, ...]
    top_scenario: str
    top_probability: float
    second_scenario: str | None
    second_probability: float | None
    scenarios: tuple[dict[str, Any], ...]
    evidence: tuple[str, ...]
    engines_used: tuple[str, ...]
    scope: str
    layers: dict[str, Any] = field(default_factory=dict)
    breakdown: dict[str, float] = field(default_factory=dict)
    freshness: dict[str, Any] = field(default_factory=dict)
    expected_move: float = 0.0
    volatility_regime: str = "moderate"
    risk_action: str = "wait"
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "paragraphs": list(self.paragraphs),
            "top_scenario": self.top_scenario,
            "top_probability": self.top_probability,
            "second_scenario": self.second_scenario,
            "second_probability": self.second_probability,
            "scenarios": list(self.scenarios),
            "evidence": list(self.evidence),
            "engines_used": list(self.engines_used),
            "scope": self.scope,
            "layers": self.layers,
            "breakdown": self.breakdown,
            "freshness": self.freshness,
            "expected_move": self.expected_move,
            "volatility_regime": self.volatility_regime,
            "risk_action": self.risk_action,
            "confidence": self.confidence,
        }


@dataclass
class _DisclosureContext:
    overlays: ForecastOverlayBundle
    symbol: str | None = None
    scope: str = "symbol"
    paragraphs: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    engines_used: list[str] = field(default_factory=list)
    confidence: float = 0.0
    risk_action: str = "wait"


class ScenarioDisclosureNarrator:
    """Build layered archetype disclosure from computed overlay outputs."""

    def from_forecast_output(
        self,
        hierarchy: ForecastOutput,
        *,
        macro_bundle: Mapping[str, Any],
        global_result: GlobalRegimeResult,
        prices: list[float] | None = None,
        scope: str = "symbol",
    ) -> ScenarioDisclosureResult:
        macro_snapshot = build_global_macro_snapshot(
            indicators=macro_bundle.get("indicators") or macro_bundle,
            global_result=global_result,
            loaded_at=str(macro_bundle.get("loaded_at") or hierarchy.as_of),
            source_timestamps=macro_bundle.get("source_timestamps") or {},
            is_stale=bool(macro_bundle.get("is_stale")),
            stale_reason=str(macro_bundle.get("stale_reason") or ""),
        )
        overlays = build_forecast_overlays(
            hierarchy=hierarchy,
            macro_snapshot=macro_snapshot,
            prices=prices,
        )
        return self.from_overlay_bundle(
            overlays,
            hierarchy=hierarchy,
            scope=scope,
        )

    def from_overlay_bundle(
        self,
        overlays: ForecastOverlayBundle,
        *,
        hierarchy: ForecastOutput | None = None,
        scope: str = "symbol",
    ) -> ScenarioDisclosureResult:
        items = self._items_from_overlay_probs(overlays, hierarchy)
        ctx = _DisclosureContext(
            overlays=overlays,
            symbol=overlays.instrument.symbol,
            scope=scope,
            confidence=hierarchy.calibrated_confidence if hierarchy else overlays.global_macro.global_regime.confidence,
            risk_action=(
                hierarchy.action_forecast.recommendation.value
                if hierarchy
                else (overlays.portfolio.recommendation if overlays.portfolio else "wait")
            ),
        )
        return self._synthesize(items, ctx)

    def from_scenario_forecast(
        self,
        scenario_forecast: ScenarioForecast,
        *,
        overlays: ForecastOverlayBundle,
        symbol: str | None = None,
        scope: str = "symbol",
        confidence: float = 0.0,
        risk_action: str = "wait",
    ) -> ScenarioDisclosureResult:
        items = self._extract_archetypes(scenario_forecast)
        ctx = _DisclosureContext(
            overlays=overlays,
            symbol=symbol,
            scope=scope,
            confidence=confidence,
            risk_action=risk_action,
        )
        return self._synthesize(items, ctx)

    def from_hierarchy_dict(
        self,
        hierarchy: Mapping[str, Any],
        *,
        macro: Mapping[str, float] | None = None,
        macro_bundle: Mapping[str, Any] | None = None,
        global_result: GlobalRegimeResult | None = None,
        rotation_scores: Sequence[SectorRotationScore] = (),
        symbol: str | None = None,
        scope: str = "symbol",
        prices: list[float] | None = None,
    ) -> ScenarioDisclosureResult:
        """Legacy entry — builds overlays from serialized hierarchy dict."""
        from app.services.prediction_hierarchy.types import ActionRecommendation

        scenario_raw = hierarchy.get("scenario_forecast") or {}
        macro_payload = macro_bundle or {"indicators": macro or {}, "loaded_at": hierarchy.get("as_of")}
        if global_result is None:
            return ScenarioDisclosureResult(
                paragraphs=(),
                top_scenario="",
                top_probability=0.0,
                second_scenario=None,
                second_probability=None,
                scenarios=(),
                evidence=(),
                engines_used=(),
                scope=scope,
            )

        macro_snapshot = build_global_macro_snapshot(
            indicators=macro_payload.get("indicators") or macro or {},
            global_result=global_result,
            loaded_at=str(macro_payload.get("loaded_at") or hierarchy.get("as_of") or ""),
            source_timestamps=macro_payload.get("source_timestamps") or {},
            is_stale=bool(macro_payload.get("is_stale")),
            stale_reason=str(macro_payload.get("stale_reason") or ""),
        )

        sector_raw = hierarchy.get("sector_regime") or {}
        sector_overlay: SectorOverlay | None = None
        if sector_raw:
            rotation_raw = sector_raw.get("rotation") or {}
            rotation = SectorRotationScore(
                sector=str(sector_raw.get("sector") or "unknown"),
                score_1w=float(rotation_raw.get("score_1w") or 0.0),
                score_1m=float(rotation_raw.get("score_1m") or 0.0),
                score_3m=float(rotation_raw.get("score_3m") or 0.0),
                composite_score=float(rotation_raw.get("composite_score") or 0.0),
                rotation_flag=SectorRotationFlag(
                    rotation_raw.get("rotation_flag") or SectorRotationFlag.NEUTRAL.value
                ),
            )
            if rotation_scores:
                rotation = rotation_scores[0]
            sector_overlay = SectorOverlay(
                sector=str(sector_raw.get("sector") or rotation.sector),
                rotation=rotation,
                sector_momentum=float(sector_raw.get("sector_momentum") or rotation.composite_score),
                dominant_sector_regime=str(
                    (sector_raw.get("regime") or {}).get("dominant_regime") or "choppy_range"
                ),
                as_of=str(hierarchy.get("as_of") or ""),
            )

        point_raw = hierarchy.get("point_forecast") or {}
        risk_raw = hierarchy.get("risk_forecast") or {}
        metrics = risk_raw.get("instrument_metrics") or risk_raw.get("metrics") or {}
        action_raw = hierarchy.get("action_forecast") or {}

        instrument_overlay = InstrumentOverlay(
            symbol=symbol or str(hierarchy.get("symbol") or ""),
            momentum=float(point_raw.get("momentum_score") or 0.5),
            vol_expansion=float(metrics.get("volatility_expansion_probability") or 0.0),
            tail_risk=float(metrics.get("tail_risk_score") or 0.0),
            composite_risk=float(metrics.get("composite_risk_score") or 0.0),
            realized_vol=float(metrics.get("realized_vol") or 0.0),
            liquidity_score=float(metrics.get("liquidity_risk_score") or 0.0),
            relative_strength=float(sector_raw.get("sector_momentum") or 0.0),
            regime_distribution=(sector_raw.get("regime") or {}).get("distribution") or {},
            as_of=str(hierarchy.get("as_of") or ""),
            expected_move=(float(point_raw.get("momentum_score") or 0.5) - 0.5) * 0.08,
        )

        overlay_breakdown = scenario_raw.get("overlay_breakdown") or {}
        overlay_audit = scenario_raw.get("overlay_audit") or {}
        from app.services.prediction_hierarchy.scenario_overlay import (
            ForecastOverlayBundle,
            ScenarioBreakdown,
            compute_layered_scenario_probabilities,
        )

        probs: dict[str, float] = {}
        for row in scenario_raw.get("scenarios") or []:
            if not isinstance(row, dict):
                continue
            archetype = str(row.get("scenario_type") or row.get("name") or "")
            if archetype in _ARCHETYPE_KEYS:
                probs[archetype] = float(row.get("probability") or 0.0)

        if overlay_breakdown:
            breakdown = ScenarioBreakdown(
                macro_score=float(overlay_breakdown.get("macro_score", 0.25)),
                sector_score=float(overlay_breakdown.get("sector_score", 0.25)),
                symbol_score=float(overlay_breakdown.get("symbol_score", 0.25)),
                portfolio_score=float(overlay_breakdown.get("portfolio_score", 0.25)),
            )
        else:
            _, breakdown, overlay_audit = compute_layered_scenario_probabilities(
                macro=macro_snapshot,
                sector=sector_overlay,
                instrument=instrument_overlay,
                portfolio=None,
            )

        overlays = ForecastOverlayBundle(
            global_macro=macro_snapshot,
            sector=sector_overlay,
            instrument=instrument_overlay,
            portfolio=None,
            scenario_probabilities=probs,
            breakdown=breakdown,
            audit=overlay_audit,
        )

        items: list[tuple[str, str, float, float | None]] = []
        for row in scenario_raw.get("scenarios") or []:
            if not isinstance(row, dict):
                continue
            archetype = str(row.get("scenario_type") or row.get("name") or "")
            if archetype not in _ARCHETYPE_KEYS:
                continue
            prob = float(row.get("probability") or probs.get(archetype, 0.0))
            impact = row.get("impact")
            impact_f = float(impact) if impact is not None else None
            label = str(row.get("label_ru") or _ARCHETYPE_RU.get(archetype, archetype))
            items.append((archetype, label, prob, impact_f))

        if not items:
            items = [
                (key, _ARCHETYPE_RU[key], float(probs.get(key, 0.0)), None)
                for key in _ARCHETYPE_KEYS
                if float(probs.get(key, 0.0)) > 0
            ]

        ctx = _DisclosureContext(
            overlays=overlays,
            symbol=symbol or str(hierarchy.get("symbol") or ""),
            scope=scope,
            confidence=float(hierarchy.get("calibrated_confidence") or global_result.confidence),
            risk_action=str(action_raw.get("recommendation") or ActionRecommendation.WAIT.value),
        )
        return self._synthesize(items, ctx)

    def from_market_engines(
        self,
        *,
        macro: Mapping[str, float],
        macro_bundle: Mapping[str, Any] | None = None,
        global_result: GlobalRegimeResult,
        rotation_scores: Sequence[SectorRotationScore],
        aggregated_archetypes: Mapping[str, float] | None = None,
    ) -> ScenarioDisclosureResult:
        """Market-wide disclosure — global macro layer only for scenario mix."""
        bundle = macro_bundle or {"indicators": macro, "loaded_at": ""}
        macro_snapshot = build_global_macro_snapshot(
            indicators=bundle.get("indicators") or macro,
            global_result=global_result,
            loaded_at=str(bundle.get("loaded_at") or ""),
            source_timestamps=bundle.get("source_timestamps") or {},
            is_stale=bool(bundle.get("is_stale")),
            stale_reason=str(bundle.get("stale_reason") or ""),
        )

        vix = macro.get("vix")
        vol_proxy = macro_snapshot.vol_proxy
        momentum_proxy = 0.5
        if rotation_scores:
            leader = rotation_scores[0]
            momentum_proxy = 0.5 + max(-0.25, min(0.25, leader.composite_score * 5))

        regime_dist = macro_snapshot.regime_distribution

        if aggregated_archetypes:
            probs = {k: float(aggregated_archetypes.get(k, 0.0)) for k in _ARCHETYPE_KEYS}
            total = sum(probs.values())
            if total > 0:
                probs = {k: round(v / total, 4) for k, v in probs.items()}
        else:
            probs = _narrative_scenario_probabilities(
                vol=vol_proxy,
                momentum=momentum_proxy,
                tail_risk=macro_snapshot.tail_risk,
                composite_risk=macro_snapshot.composite_risk,
                regime_distribution=regime_dist,
            )

        sector_overlay = None
        if rotation_scores:
            leader = rotation_scores[0]
            sector_overlay = SectorOverlay(
                sector=leader.sector,
                rotation=leader,
                sector_momentum=leader.composite_score,
                dominant_sector_regime="market_aggregate",
                as_of=str(bundle.get("loaded_at") or ""),
                rank=leader.rank,
            )

        instrument_overlay = InstrumentOverlay(
            symbol="MARKET",
            momentum=momentum_proxy,
            vol_expansion=vol_proxy,
            tail_risk=macro_snapshot.tail_risk,
            composite_risk=macro_snapshot.composite_risk,
            realized_vol=vol_proxy / 8.0,
            liquidity_score=0.0,
            relative_strength=0.0,
            regime_distribution=regime_dist,
            as_of=str(bundle.get("loaded_at") or ""),
        )

        from app.services.prediction_hierarchy.scenario_overlay import ForecastOverlayBundle, ScenarioBreakdown

        overlays = ForecastOverlayBundle(
            global_macro=macro_snapshot,
            sector=sector_overlay,
            instrument=instrument_overlay,
            portfolio=None,
            scenario_probabilities=probs,
            breakdown=ScenarioBreakdown(0.55, 0.25, 0.15, 0.05),
            audit={"source": "market_engines", "vix": vix},
        )

        items = [
            (key, _ARCHETYPE_RU[key], float(probs.get(key, 0.0)), None)
            for key in _ARCHETYPE_KEYS
            if float(probs.get(key, 0.0)) > 0
        ]
        ctx = _DisclosureContext(
            overlays=overlays,
            symbol=None,
            scope="market",
            confidence=global_result.confidence,
            risk_action="wait",
        )
        return self._synthesize(items, ctx)

    def _items_from_overlay_probs(
        self,
        overlays: ForecastOverlayBundle,
        hierarchy: ForecastOutput | None,
    ) -> list[tuple[str, str, float, float | None]]:
        if hierarchy is not None:
            return self._extract_archetypes(hierarchy.scenario_forecast)
        return [
            (key, _ARCHETYPE_RU[key], float(overlays.scenario_probabilities.get(key, 0.0)), None)
            for key in _ARCHETYPE_KEYS
            if float(overlays.scenario_probabilities.get(key, 0.0)) > 0
        ]

    def _extract_archetypes(
        self,
        scenario_forecast: ScenarioForecast,
    ) -> list[tuple[str, str, float, float | None]]:
        items: list[tuple[str, str, float, float | None]] = []
        for scenario in scenario_forecast.scenarios:
            if scenario.scenario_type not in _ARCHETYPE_KEYS:
                continue
            items.append(
                (
                    scenario.scenario_type,
                    scenario.label_ru or _ARCHETYPE_RU.get(scenario.scenario_type, scenario.name),
                    float(scenario.probability),
                    float(scenario.impact) if scenario.impact is not None else None,
                )
            )
        return items

    def _synthesize(
        self,
        items: Sequence[tuple[str, str, float, float | None]],
        ctx: _DisclosureContext,
    ) -> ScenarioDisclosureResult:
        if not items:
            return ScenarioDisclosureResult(
                paragraphs=(),
                top_scenario="",
                top_probability=0.0,
                second_scenario=None,
                second_probability=None,
                scenarios=(),
                evidence=(),
                engines_used=(),
                scope=ctx.scope,
            )

        ranked = sorted(items, key=lambda row: row[2], reverse=True)
        top_key, top_label, top_prob, top_impact = ranked[0]
        second_key: str | None = None
        second_prob: float | None = None
        second_label: str | None = None
        second_impact: float | None = None

        if len(ranked) >= 2:
            sk, sl, sp, si = ranked[1]
            if top_prob - sp < CLOSE_SCENARIO_THRESHOLD:
                second_key, second_label, second_prob, second_impact = sk, sl, sp, si

        self._record_evidence(ctx, top_key)
        ctx.paragraphs.extend(
            self._build_layered_narrative(
                top_key,
                top_label,
                top_prob,
                top_impact,
                second_key,
                second_label,
                second_prob,
                second_impact,
                ctx,
            )
        )

        scenario_rows = tuple(
            {
                "archetype": key,
                "label_ru": label,
                "probability": prob,
                "impact": impact,
            }
            for key, label, prob, impact in ranked
        )

        overlays = ctx.overlays
        freshness = {
            "global_macro": {
                "loaded_at": overlays.global_macro.loaded_at,
                "source_timestamps": dict(overlays.global_macro.source_timestamps),
                "is_stale": overlays.global_macro.is_stale,
                "stale_reason": overlays.global_macro.stale_reason,
            },
            "sector": overlays.sector.as_of if overlays.sector else None,
            "instrument": overlays.instrument.as_of,
            "portfolio": overlays.portfolio.as_of if overlays.portfolio else None,
        }

        return ScenarioDisclosureResult(
            paragraphs=tuple(ctx.paragraphs),
            top_scenario=top_key,
            top_probability=top_prob,
            second_scenario=second_key,
            second_probability=second_prob,
            scenarios=scenario_rows,
            evidence=tuple(ctx.evidence),
            engines_used=tuple(dict.fromkeys(ctx.engines_used)),
            scope=ctx.scope,
            layers={
                "global_macro": overlays.global_macro.to_dict(),
                "sector": overlays.sector.to_dict() if overlays.sector else None,
                "instrument": overlays.instrument.to_dict(),
                "portfolio": overlays.portfolio.to_dict() if overlays.portfolio else None,
            },
            breakdown=overlays.breakdown.to_dict(),
            freshness=freshness,
            expected_move=overlays.instrument.expected_move,
            volatility_regime=overlays.instrument.volatility_regime,
            risk_action=ctx.risk_action,
            # calibrated_confidence — trust in the overall forecast model (header «уверенность»)
            confidence=ctx.confidence,
        )

    def _build_layered_narrative(
        self,
        top_key: str,
        top_label: str,
        top_prob: float,
        top_impact: float | None,
        second_key: str | None,
        second_label: str | None,
        second_prob: float | None,
        second_impact: float | None,
        ctx: _DisclosureContext,
    ) -> list[str]:
        overlays = ctx.overlays
        symbol = ctx.symbol or overlays.instrument.symbol
        is_market = ctx.scope == "market"

        return [
            self._compact_verdict(
                symbol,
                top_key,
                top_label,
                top_prob,
                top_impact,
                ctx,
                is_market=is_market,
            ),
            self._compact_why(overlays, top_key, is_market=is_market),
            self._compact_triggers(
                overlays,
                top_key,
                top_prob,
                second_label,
                second_prob,
                is_market=is_market,
            ),
            self._compact_action(ctx),
        ]

    def _scenario_position_meaning(self, archetype: str, *, is_market: bool) -> str:
        if archetype == "pessimistic":
            return "защитный режим и меньший риск" if is_market else "не наращивать позицию"
        if archetype == "optimistic":
            return "риск можно брать выборочно" if is_market else "позиция допустима только малым размером"
        if archetype == "classic":
            return "работать от диапазона" if is_market else "не гнаться за пробоем"
        return "базовый план без агрессивного входа"

    def _compact_verdict(
        self,
        symbol: str,
        top_key: str,
        top_label: str,
        top_prob: float,
        top_impact: float | None,
        ctx: _DisclosureContext,
        *,
        is_market: bool,
    ) -> str:
        subject = "Рынок" if is_market else symbol
        action_ru = translate_risk_action(ctx.risk_action)
        meaning = self._scenario_position_meaning(top_key, is_market=is_market)
        impact_text = ""
        if top_impact is not None and abs(top_impact) >= 0.003:
            impact_text = f", расчётный ход {top_impact * 100:+.1f}%"
        return _sentence(
            f"Вердикт - {subject}: {top_label.lower()} сценарий {_pct(top_prob)} "
            f"означает {meaning}{impact_text}. Действие — {action_ru}"
        )

    def _compact_why(
        self,
        overlays: ForecastOverlayBundle,
        archetype: str,
        *,
        is_market: bool,
    ) -> str:
        inst = overlays.instrument
        move_pct = inst.expected_move * 100.0
        vol_ru = translate_volatility_regime(inst.volatility_regime).split(",")[0]
        expansion_pct = round(inst.vol_expansion * 100.0)
        momentum_pct = round(inst.momentum * 100.0)

        lead = (
            f"По инструменту {_momentum_phrase(inst.momentum).lower()}, "
            f"базовый расчётный ход около {move_pct:+.1f}%"
        )
        vol_part = f"режим волатильности — {vol_ru.lower()}"
        if expansion_pct >= 35:
            vol_part += f", вероятность расширения диапазона около {expansion_pct}%"
        elif expansion_pct <= 5:
            vol_part += ", расширение волатильности маловероятно"
        else:
            vol_part += f", риск расширения диапазона около {expansion_pct}%"

        if overlays.sector is not None and not is_market:
            sector_ru = translate_sector_name(overlays.sector.sector)
            bp = overlays.sector.momentum_bp
            sector_part = (
                f"Сектор «{sector_ru}» даёт импульс {bp:+.0f} б.п. за месяц"
                if abs(bp) >= 10
                else f"Сектор «{sector_ru}» без выраженного импульса"
            )
            body = f"{lead}, {vol_part}. {sector_part}."
        elif is_market:
            macro = overlays.global_macro
            dom = _compact_regime_ru(macro.global_regime.dominant_regime)
            macro_bits = [f"макро-режим — {dom.lower()}"]
            vix = macro.indicators.get("vix")
            cpi = macro.indicators.get("cpi")
            if vix is not None:
                macro_bits.append(f"VIX около {vix:.1f}")
            if cpi is not None:
                macro_bits.append(f"инфляция около {cpi:.1f}%")
            body = f"{lead}, {vol_part}. На рынке в целом {', '.join(macro_bits)}."
        elif archetype in {"pessimistic", "classic"} and inst.tail_risk >= 0.35:
            body = (
                f"{lead}, {vol_part}. {_tail_risk_phrase(inst.tail_risk).capitalize()}, "
                f"{_liquidity_phrase(inst.liquidity_score)}."
            )
        else:
            body = f"{lead}, {vol_part} (импульс модели {momentum_pct}%)."

        return f"Почему - {body.strip()}"

    def _compact_triggers(
        self,
        overlays: ForecastOverlayBundle,
        archetype: str,
        top_prob: float,
        second_label: str | None,
        second_prob: float | None,
        *,
        is_market: bool,
    ) -> str:
        inst = overlays.instrument
        expansion_pct = round(inst.vol_expansion * 100.0)
        triggers: list[str] = []
        if archetype in {"pessimistic", "classic"}:
            triggers.append(
                "Взгляд смягчится, если импульс устойчиво выше 60% при снижении "
                f"вероятности расширения волатильности ниже 30% (сейчас около {expansion_pct}%)"
            )
        else:
            triggers.append(
                "Сценарий ослабнет при падении импульса ниже 45% или росте "
                f"вероятности расширения волатильности выше 45% (сейчас около {expansion_pct}%)"
            )
        if second_label is not None and second_prob is not None:
            gap = top_prob - second_prob
            triggers.append(
                f"Если {second_label.lower()} сблизится с лидером (разрыв сейчас {_pct(gap)}), "
                "пересмотрите размер позиции"
            )
        elif is_market:
            vix = overlays.global_macro.indicators.get("vix")
            if vix is not None:
                triggers.append(
                    f"Резкий сдвиг VIX за пределы 15–25 (сейчас {vix:.1f}) изменит базовый сценарий"
                )
        elif inst.tail_risk >= 0.35:
            tail_pct = round(inst.tail_risk * 100.0)
            triggers.append(
                f"Устойчивое снижение хвостового риска ниже 35% (сейчас около {tail_pct}%) "
                "поддержит более конструктивный исход"
            )
        return "Что изменит взгляд - " + " ".join(triggers[:2])

    def _compact_action(self, ctx: _DisclosureContext) -> str:
        action_ru = translate_risk_action(ctx.risk_action)
        if ctx.risk_action in {"reduce_size", "hedge", "avoid"}:
            plain = "разумно снизить размер или не наращивать риск"
        elif ctx.risk_action == "enter_small_size":
            plain = "допустим лишь осторожный вход малым объёмом"
        elif ctx.risk_action == "enter_normal_size":
            plain = "можно удерживать или наращивать позицию по плану"
        elif ctx.risk_action == "wait":
            plain = "лучше выждать подтверждения, без новой сделки"
        else:
            plain = "удерживать текущую позицию без агрессивных изменений"
        return _sentence(f"Действие - {plain}. Рекомендация модели: {action_ru}.")

    def _lead_paragraph(
        self,
        symbol: str,
        top_label: str,
        top_prob: float,
        top_impact: float | None,
        ctx: _DisclosureContext,
        *,
        is_market: bool,
    ) -> str:
        overlays = ctx.overlays
        macro = overlays.global_macro
        instrument = overlays.instrument
        dom_ru = translate_global_regime(macro.global_regime.dominant_regime)
        vol_ru = translate_volatility_regime(instrument.volatility_regime)
        action_ru = translate_risk_action(ctx.risk_action)
        impact_text = _impact_phrase(top_impact)

        if is_market:
            subject = "По рынку в целом"
        else:
            subject = f"Для {symbol}"

        parts = [
            f"{subject} наиболее вероятен {top_label.lower()} сценарий ({_pct_plain(top_prob)})"
        ]
        if impact_text:
            parts[0] += f": {impact_text}"

        macro_clause = f"Общий фон — {dom_ru}"
        instrument_clause = f"по инструменту {_momentum_phrase(instrument.momentum).lower()}"
        vol_clause = f"волатильность {vol_ru.split(',')[0]}"
        if instrument.vol_expansion >= 0.35:
            vol_clause += " и может расшириться"

        text = (
            f"{parts[0]}. {macro_clause}, но {instrument_clause}, а {vol_clause} — "
            f"поэтому рекомендуется {action_ru}."
        )
        return _sentence(text)

    def _global_macro_paragraph(self, macro: GlobalMacroSnapshot) -> str:
        dom = macro.global_regime.dominant_regime
        dom_ru = translate_global_regime(dom)
        dom_prob = macro.global_regime.distribution.get(dom, 0.0)

        sentences = [
            f"На глобальном уровне доминирует {dom_ru} "
            f"({_pct_plain(dom_prob)} вероятности, уверенность оценки {_pct(macro.global_regime.confidence)})"
        ]

        vix = macro.indicators.get("vix")
        if vix is not None:
            if vix < 15:
                vix_desc = f"индекс страха VIX на уровне {vix:.1f} указывает на спокойный рынок"
            elif vix < 20:
                vix_desc = f"VIX {vix:.1f} — волатильность умеренная, без явного стресса"
            elif vix < 28:
                vix_desc = f"VIX {vix:.1f} — инвесторам стоит проявлять осторожность"
            else:
                vix_desc = f"VIX {vix:.1f} — высокая неопределённость и стресс на рынке"
            sentences.append(vix_desc)

        cpi = macro.indicators.get("cpi")
        if cpi is not None:
            if cpi >= 4.0:
                cpi_desc = f"инфляционный фон остаётся повышенным (около {cpi:.1f}%)"
            elif cpi >= 2.5:
                cpi_desc = f"инфляция умеренная (около {cpi:.1f}%)"
            else:
                cpi_desc = f"инфляционное давление сдержанное (около {cpi:.1f}%)"
            sentences.append(cpi_desc)

        return _sentence(" ".join(sentences))

    def _sector_paragraph(self, sector: SectorOverlay, symbol: str) -> str:
        sector_ru = translate_sector_name(sector.sector)
        flag_ru = translate_rotation_flag(sector.rotation.rotation_flag.value)
        regime_ru = translate_sector_regime(sector.dominant_sector_regime)
        momentum_bp = sector.momentum_bp

        if abs(momentum_bp) >= 50:
            momentum_desc = (
                f"сектор демонстрирует заметный импульс ({momentum_bp:+.0f} б.п. за месяц)"
            )
        elif abs(momentum_bp) >= 10:
            momentum_desc = f"импульс сектора умеренный ({momentum_bp:+.1f} б.п.)"
        else:
            momentum_desc = "импульс сектора слабый, без выраженного направления"

        return _sentence(
            f"Для {symbol} релевантен сектор «{sector_ru}»: {flag_ru}, "
            f"{momentum_desc}, режим — {regime_ru}."
        )

    def _instrument_paragraph(
        self,
        instrument: InstrumentOverlay,
        symbol: str,
        ctx: _DisclosureContext,
    ) -> str:
        vol_ru = translate_volatility_regime(instrument.volatility_regime)
        move_pct = instrument.expected_move * 100.0
        if abs(move_pct) >= 0.2:
            move_text = f"ожидаемый ход около {move_pct:+.1f}%"
        else:
            move_text = "ожидаемый ход минимальный"

        tail_desc = _tail_risk_phrase(instrument.tail_risk)
        liq_desc = _liquidity_phrase(instrument.liquidity_score)

        realized_pct = instrument.realized_vol * 100.0
        vol_level = (
            f"реализованная волатильность {realized_pct:.1f}%"
            if realized_pct >= 0.5
            else "волатильность на исторических данных низкая"
        )

        return _sentence(
            f"По самому инструменту {symbol}: {_momentum_phrase(instrument.momentum).lower()}, "
            f"{vol_level}, режим волатильности — {vol_ru}, {move_text}, "
            f"{tail_desc}, {liq_desc}."
        )

    def _portfolio_paragraph(self, portfolio: PortfolioOverlay, symbol: str) -> str:
        action_ru = translate_risk_action(portfolio.recommendation)
        exposure_pct = portfolio.exposure_weight * 100.0

        risk_level = "повышенный" if portfolio.portfolio_risk_score >= 0.5 else "умеренный"

        return _sentence(
            f"Для вашего портфеля доля {symbol} составляет около {exposure_pct:.1f}%, "
            f"риск портфеля {risk_level}, рекомендация — {action_ru}."
        )

    def _alternative_paragraph(
        self,
        second_label: str,
        second_prob: float,
        top_prob: float,
        second_impact: float | None,
        second_key: str,
        ctx: _DisclosureContext,
    ) -> str:
        gap = top_prob - second_prob
        second_impact_text = _impact_phrase(second_impact)
        alt_implications = _ARCHETYPE_IMPLICATIONS.get(
            second_key, "альтернативное распределение риска"
        )

        parts = [
            f"Альтернатива почти столь же вероятна — {second_label.lower()} "
            f"({_pct_plain(second_prob)}, разрыв с лидером {_pct(gap)})"
        ]
        if second_impact_text:
            parts.append(f"при этом исходе {second_impact_text}")
        parts.append(f"в таком случае {alt_implications}")

        return _sentence(". ".join(parts))

    def _rationale_paragraph(
        self,
        archetype: str,
        label: str,
        probability: float,
        impact: float | None,
        ctx: _DisclosureContext,
    ) -> str:
        overlays = ctx.overlays
        fit_reasons: list[str] = []

        if archetype == "pessimistic":
            fit_reasons.append(
                "секторный и инструментальный импульс усиливают хвостовой риск при текущем макро-фоне"
            )
        elif archetype == "realistic":
            fit_reasons.append("базовый сценарий согласован с доминирующим режимом и текущим импульсом")
        elif archetype == "optimistic":
            fit_reasons.append(
                "сочетание благоприятного макро-фона и позитивного секторного или инструментального импульса"
            )
        elif archetype == "classic":
            fit_reasons.append(
                "нейтральный импульс и стабильная волатильность указывают на возврат к среднему"
            )

        if overlays.sector and overlays.sector.momentum_bp > 50 and archetype == "optimistic":
            fit_reasons.append("секторный импульс поддерживает благоприятный исход")
        if overlays.instrument.momentum < 0.4 and archetype == "pessimistic":
            fit_reasons.append("слабый импульс инструмента повышает вес неблагоприятного сценария")

        reason_text = fit_reasons[0] if fit_reasons else "расчётные веса согласуются с текущими данными"

        impact_clause = ""
        if impact is not None:
            move = impact * 100.0
            if abs(move) >= 0.3:
                direction_word = "рост" if move > 0 else "снижение"
                impact_clause = f" Расчётный эффект — {direction_word} порядка {abs(move):.1f}%."

        implications = _ARCHETYPE_IMPLICATIONS.get(
            archetype,
            "нейтральное распределение риска по классам активов",
        )
        scope_hint = f" для {ctx.symbol}" if ctx.symbol and ctx.scope == "symbol" else ""

        return _sentence(
            f"Почему выделен {label.lower()} сценарий ({_pct_plain(probability)}): "
            f"{reason_text}.{impact_clause} На практике{scope_hint} {implications}."
        )

    def _record_evidence(self, ctx: _DisclosureContext, archetype: str) -> None:
        overlays = ctx.overlays
        macro = overlays.global_macro
        ctx.evidence.append(f"layer.global_macro.dominant={macro.global_regime.dominant_regime}")
        ctx.evidence.append(f"layer.global_macro.loaded_at={macro.loaded_at}")

        vix = macro.indicators.get("vix")
        if vix is not None:
            ctx.evidence.append(f"layer.global_macro.vix={vix:.1f}")

        cpi = macro.indicators.get("cpi")
        if cpi is not None:
            ctx.evidence.append(f"layer.global_macro.cpi={cpi:.2f}")

        if overlays.sector is not None:
            ctx.evidence.append(f"layer.sector={overlays.sector.sector}")
            ctx.evidence.append(f"layer.sector.momentum_bp={overlays.sector.momentum_bp}")

        inst = overlays.instrument
        ctx.evidence.append(f"layer.instrument.momentum={inst.momentum:.4f}")
        ctx.evidence.append(f"layer.instrument.vol_regime={inst.volatility_regime}")
        ctx.evidence.append(f"layer.instrument.expected_move={inst.expected_move:.6f}")

        if overlays.portfolio is not None and overlays.portfolio.has_exposure:
            ctx.evidence.append(f"layer.portfolio.exposure={overlays.portfolio.exposure_weight:.4f}")

        breakdown = overlays.breakdown
        ctx.evidence.append(
            "layer.breakdown="
            f"macro:{breakdown.macro_score},sector:{breakdown.sector_score},"
            f"symbol:{breakdown.symbol_score},portfolio:{breakdown.portfolio_score}"
        )
        ctx.evidence.append(f"audit.overlay={overlays.audit}")
        ctx.evidence.append(f"top_archetype={archetype}")
