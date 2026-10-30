"""Deterministic market-wide prediction summary from computed forecast engines."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from app.services.prediction_hierarchy.scenario_summary import (
    describe_top_scenarios,
    rank_scenario_probabilities,
)
from app.services.prediction_hierarchy.types import (
    GlobalRegimeLabel,
    GlobalRegimeResult,
    SectorRotationFlag,
    SectorRotationScore,
)

_GLOBAL_RU: dict[str, str] = {
    GlobalRegimeLabel.RISK_ON.value: "режим риска (risk-on)",
    GlobalRegimeLabel.RISK_OFF.value: "режим защиты (risk-off)",
    GlobalRegimeLabel.MACRO_UNCERTAINTY.value: "макро-неопределённость",
    GlobalRegimeLabel.CREDIT_STRESS.value: "стресс на кредитном рынке",
    GlobalRegimeLabel.INFLATION_SHOCK_REGIME.value: "инфляционный шок",
}

_ROTATION_RU: dict[str, str] = {
    SectorRotationFlag.SECTORS_STRENGTHENING.value: "секторы усиливаются",
    SectorRotationFlag.SECTORS_WEAKENING.value: "секторы ослабевают",
    SectorRotationFlag.ROTATION_IN_PROGRESS.value: "ротация секторов в процессе",
    SectorRotationFlag.NEUTRAL.value: "нейтральная ротация",
}

_SECTOR_RU: dict[str, str] = {
    "technology": "технологии",
    "financials": "финансы",
    "energy": "энергетика",
    "consumer_discretionary": "потребительский сектор",
    "communication_services": "коммуникации",
    "indices": "индексы",
    "macro_hedge": "макро-хедж",
    "digital_assets": "цифровые активы",
    "materials": "материалы",
}

_COVERAGE_RU: dict[str, str] = {
    "MOEX": "российский рынок",
    "US_equities": "акции США",
    "crypto": "крипторынок",
}


def _pct(probability: float) -> str:
    return f"{round(max(0.0, min(1.0, probability)) * 100.0, 1)}%"


@dataclass(frozen=True, slots=True)
class MarketCoverage:
    """Which exchanges/markets have real computed data."""

    markets: tuple[str, ...]
    moex_symbols: tuple[str, ...] = ()
    us_symbols: tuple[str, ...] = ()
    crypto_symbols: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MarketPredictionSummaryResult:
    """Structured + plain-text market prediction summary."""

    paragraphs: tuple[str, ...]
    coverage: tuple[str, ...]
    engines_used: tuple[str, ...]
    evidence: tuple[str, ...]
    missing_resources: tuple[str, ...]
    confidence_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "paragraphs": list(self.paragraphs),
            "coverage": list(self.coverage),
            "engines_used": list(self.engines_used),
            "evidence": list(self.evidence),
            "missing_resources": list(self.missing_resources),
            "confidence_pct": self.confidence_pct,
        }


@dataclass
class _SynthesisContext:
    global_result: GlobalRegimeResult | None
    macro: Mapping[str, float]
    rotation_scores: Sequence[SectorRotationScore]
    coverage: MarketCoverage
    cross_asset_correlation: float
    paragraphs: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    engines_used: list[str] = field(default_factory=list)
    missing_resources: list[str] = field(default_factory=list)


class MarketPredictionNarrator:
    """Synthesize broad market narrative from real engine outputs only."""

    _MACRO_KEYS = ("vix", "cpi", "rate_cb", "dxy", "oil_brent", "unemployment")

    def synthesize(
        self,
        *,
        global_result: GlobalRegimeResult | None,
        macro: Mapping[str, float],
        rotation_scores: Sequence[SectorRotationScore],
        coverage: MarketCoverage,
        cross_asset_correlation: float = 0.0,
    ) -> MarketPredictionSummaryResult:
        ctx = _SynthesisContext(
            global_result=global_result,
            macro=macro,
            rotation_scores=rotation_scores,
            coverage=coverage,
            cross_asset_correlation=cross_asset_correlation,
        )
        self._collect_missing_resources(ctx)

        if not self._has_minimum_data(ctx):
            return MarketPredictionSummaryResult(
                paragraphs=(),
                coverage=coverage.markets,
                engines_used=(),
                evidence=(),
                missing_resources=tuple(ctx.missing_resources),
                confidence_pct=0.0,
            )

        self._paragraph_coverage_scope(ctx)
        if ctx.global_result is not None:
            self._paragraph_dominant_scenarios(ctx)
            self._paragraph_global_regime(ctx)
        if ctx.rotation_scores:
            self._paragraph_sector_rotation(ctx)
        self._paragraph_volatility_risk(ctx)
        self._paragraph_outlook(ctx)

        confidence = self._aggregate_confidence(ctx)
        engines = tuple(dict.fromkeys(ctx.engines_used))

        return MarketPredictionSummaryResult(
            paragraphs=tuple(ctx.paragraphs),
            coverage=coverage.markets,
            engines_used=engines,
            evidence=tuple(ctx.evidence),
            missing_resources=tuple(ctx.missing_resources),
            confidence_pct=confidence,
        )

    def _has_minimum_data(self, ctx: _SynthesisContext) -> bool:
        if ctx.global_result is not None and ctx.global_result.confidence > 0:
            return True
        if ctx.rotation_scores:
            return True
        return any(key in ctx.macro and ctx.macro[key] is not None for key in ("vix", "cpi", "rate_cb"))

    def _collect_missing_resources(self, ctx: _SynthesisContext) -> None:
        missing: list[str] = []
        macro = ctx.macro

        for key in self._MACRO_KEYS:
            if key not in macro or macro.get(key) is None:
                missing.append(f"macro_indicators.{key}")

        if "MOEX" not in ctx.coverage.markets:
            missing.append("market_ohlcv.moex (SBER, GAZP, LKOH, GMKN и др.)")
        if "US_equities" not in ctx.coverage.markets:
            missing.append("market_ohlcv.us_equities (SPY, QQQ и секторные ETF)")

        if not ctx.rotation_scores:
            missing.append("sector_mapping + market_ohlcv.1d для SectorRegimeEngine")

        if ctx.global_result is None:
            missing.append("global_regime.classify (macro snapshot для GlobalMacroRegimeEngine)")

        if ctx.global_result and ctx.global_result.credit_spread_proxy is None:
            if "credit_spread" not in macro:
                missing.append("credit_spread.hy_oas (спред высокодоходных облигаций, FRED BAMLH0A0HYM2)")

        if "macro_indicators.rate_cb" in missing and "MOEX" in ctx.coverage.markets:
            missing.append("macro_indicators.rate_cb_ru (ключевая ставка ЦБ РФ)")

        ctx.missing_resources = missing

    def _paragraph_coverage_scope(self, ctx: _SynthesisContext) -> None:
        labels = [_COVERAGE_RU.get(m, m) for m in ctx.coverage.markets]
        if labels:
            scope = ", ".join(labels)
            text = (
                f"Смотрим сразу несколько рынков: {scope}. "
                "Ниже — что из этого следует обычным языком, без внутренних ярлыков модели."
            )
        else:
            text = "Картина рынка собрана по тем ценам и макроцифрам, которые сейчас есть на платформе."
        ctx.paragraphs.append(text)
        ctx.evidence.append(f"coverage={','.join(ctx.coverage.markets) or 'limited'}")

    def _paragraph_dominant_scenarios(self, ctx: _SynthesisContext) -> None:
        result = ctx.global_result
        assert result is not None

        ranked = rank_scenario_probabilities(result.distribution, label_ru=_GLOBAL_RU)
        scenario_text = describe_top_scenarios(ranked)
        if not scenario_text:
            return

        ctx.paragraphs.append(scenario_text)
        ctx.engines_used.append("GlobalMacroRegimeEngine")
        if ranked:
            top_key, _, top_prob = ranked[0]
            ctx.evidence.append(f"scenario_top={top_key}")
            ctx.evidence.append(f"prob_{top_key}={top_prob:.4f}")
            if len(ranked) >= 2:
                second_key, _, second_prob = ranked[1]
                ctx.evidence.append(f"scenario_second={second_key}")
                ctx.evidence.append(f"prob_{second_key}={second_prob:.4f}")

    def _paragraph_global_regime(self, ctx: _SynthesisContext) -> None:
        result = ctx.global_result
        assert result is not None

        dominant_ru = _GLOBAL_RU.get(result.dominant_regime, result.dominant_regime)
        dom_prob = result.distribution.get(result.dominant_regime, 0.0)
        risk_off_prob = result.distribution.get(GlobalRegimeLabel.RISK_OFF.value, 0.0)
        macro_unc_prob = result.distribution.get(GlobalRegimeLabel.MACRO_UNCERTAINTY.value, 0.0)

        vix = ctx.macro.get("vix")
        vix_clause = ""
        if vix is not None and 0 < vix < 80:
            if vix >= 30:
                vix_clause = f" Страх на рынке высокий: индекс волатильности около {vix:.0f}."
            elif vix <= 18:
                vix_clause = f" Рынок спокойный: индекс волатильности около {vix:.0f}."
            else:
                vix_clause = f" Волатильность обычная, индекс около {vix:.0f}."

        cpi = ctx.macro.get("cpi")
        inflation_clause = ""
        if cpi is not None and 0 < cpi < 25:
            if cpi > 3.5:
                inflation_clause = f" Цены в экономике всё ещё растут заметно (ориентир инфляции около {cpi:.1f}%)."
            else:
                inflation_clause = f" Инфляция не выглядит экстремальной (ориентир около {cpi:.1f}%)."

        world_gdp = ctx.macro.get("wb_world_gdp_growth")
        growth_clause = ""
        if world_gdp is not None and -10 < world_gdp < 15:
            if world_gdp < 2.0:
                growth_clause = f" Мировая экономика растёт медленно, около {world_gdp:.1f}% в год."
            else:
                growth_clause = f" Мировой рост около {world_gdp:.1f}% в год."

        text = (
            f"Сейчас рынок скорее в режиме «{dominant_ru}» "
            f"(шанс этого режима {_pct(dom_prob)}, уверенность оценки {_pct(result.confidence)})."
            f"{vix_clause}{inflation_clause}{growth_clause} "
            f"Сценарий «уход в защиту» — {_pct(risk_off_prob)}, "
            f"сценарий «непонятно, что будет дальше» — {_pct(macro_unc_prob)}."
        )
        ctx.paragraphs.append(text)
        ctx.engines_used.append("GlobalMacroRegimeEngine")
        ctx.evidence.extend(
            [
                f"global_regime.dominant={result.dominant_regime}",
                f"global_regime.confidence={result.confidence:.4f}",
                f"prob_{result.dominant_regime}={dom_prob:.4f}",
            ]
            + (
                [f"credit_spread_proxy={result.credit_spread_proxy:.4f}"]
                if result.credit_spread_proxy is not None
                else []
            )
        )
        if vix is not None:
            ctx.evidence.append(f"macro_indicators.vix={vix:.1f}")
        if world_gdp is not None:
            ctx.evidence.append(f"macro_indicators.wb_world_gdp_growth={world_gdp:.2f}")

    def _paragraph_sector_rotation(self, ctx: _SynthesisContext) -> None:
        leader = ctx.rotation_scores[0]
        lagger = ctx.rotation_scores[-1]
        leader_ru = _SECTOR_RU.get(leader.sector, leader.sector)
        lagger_ru = _SECTOR_RU.get(lagger.sector, lagger.sector)
        flag_ru = _ROTATION_RU.get(leader.rotation_flag.value, leader.rotation_flag.value)

        text = (
            f"Среди секторов сейчас сильнее выглядит {leader_ru}, слабее — {lagger_ru}. "
            f"Это {flag_ru}."
        )

        if leader.rotation_flag == SectorRotationFlag.SECTORS_WEAKENING:
            text += " Деньги скорее уходят из слабых отраслей."
        elif leader.rotation_flag == SectorRotationFlag.SECTORS_STRENGTHENING:
            text += " Капитал держится в лидерах, а не размазывается по всему рынку."
        elif leader.rotation_flag == SectorRotationFlag.ROTATION_IN_PROGRESS:
            text += " Идёт смена лидеров — выбирать бумаги стоит точечно, не «весь рынок сразу»."

        ctx.paragraphs.append(text)
        ctx.engines_used.append("SectorRegimeEngine")
        ctx.evidence.extend(
            [
                f"sector_leader={leader.sector}",
                f"rotation_flag={leader.rotation_flag.value}",
                f"composite_score_1m={leader.composite_score:.4f}",
                f"score_1w={leader.score_1w:.4f}",
                f"score_3m={leader.score_3m:.4f}",
            ]
        )

    def _paragraph_volatility_risk(self, ctx: _SynthesisContext) -> None:
        """GLOBAL market-wide paragraph — same text across tickers when macro inputs unchanged (by design)."""
        vix = ctx.macro.get("vix")
        cross_corr = ctx.cross_asset_correlation

        vol_regime = "умеренная"
        if vix is not None:
            if vix >= 28:
                vol_regime = "повышенная"
            elif vix <= 16:
                vol_regime = "низкая"

        corr_clause = ""
        if cross_corr >= 0.55:
            corr_clause = " Разные активы двигаются слишком похоже — прятаться диверсификацией сложнее."
        elif cross_corr > 0:
            corr_clause = " Связь между активами умеренная, рынок не схлопнулся в одно движение."

        text = f"Качки цен сейчас {vol_regime}.{corr_clause}"
        ctx.paragraphs.append(text)
        ctx.engines_used.append("ForecastOutputBuilder")
        if vix is not None:
            ctx.evidence.append(f"macro_indicators.vix={vix:.1f}")
        if cross_corr > 0:
            ctx.evidence.append(f"cross_asset_correlation={cross_corr:.4f}")

    def _paragraph_outlook(self, ctx: _SynthesisContext) -> None:
        """GLOBAL baseline outlook — not per-ticker; identical when regime/rotation unchanged."""
        parts: list[str] = []

        if ctx.global_result is not None:
            dom = ctx.global_result.dominant_regime
            if dom in {
                GlobalRegimeLabel.RISK_OFF.value,
                GlobalRegimeLabel.CREDIT_STRESS.value,
                GlobalRegimeLabel.MACRO_UNCERTAINTY.value,
            }:
                parts.append(
                    "Практический тон: меньше риска, больше запаса по деньгам, не гнаться за всем рынком."
                )
            elif dom == GlobalRegimeLabel.INFLATION_SHOCK_REGIME.value:
                parts.append(
                    "Практический тон: осторожнее с бумагами роста, ближе к сырью и коротким ставкам."
                )
            else:
                parts.append(
                    "Практический тон: риск можно держать, но без фанатизма и с взглядом на сюрпризы в макроданных."
                )

        if ctx.rotation_scores:
            leader = ctx.rotation_scores[0]
            leader_ru = _SECTOR_RU.get(leader.sector, leader.sector)
            parts.append(f"Имеет смысл смотреть в сторону сектора «{leader_ru}», если движение подтвердится.")

        if "MOEX" in ctx.coverage.markets and "US_equities" not in ctx.coverage.markets:
            parts.append("В кадре в основном российский рынок — американские акции в этой сводке слабее представлены.")
        elif "MOEX" not in ctx.coverage.markets and "US_equities" in ctx.coverage.markets:
            parts.append("В кадре в основном американские акции — российский рынок в этой сводке слабее представлен.")

        if parts:
            ctx.paragraphs.append(" ".join(parts))
            ctx.engines_used.append("ActionForecastEngine")

    def _aggregate_confidence(self, ctx: _SynthesisContext) -> float:
        scores: list[float] = []
        if ctx.global_result is not None:
            scores.append(ctx.global_result.confidence)
        if ctx.rotation_scores:
            leader = ctx.rotation_scores[0]
            sector_conf = min(0.95, 0.55 + abs(leader.composite_score) * 2)
            scores.append(sector_conf)
        if ctx.macro.get("vix") is not None:
            scores.append(0.70)
        if not scores:
            return 0.0
        return round(sum(scores) / len(scores) * 100, 1)
