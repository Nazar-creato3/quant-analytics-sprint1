"""Daily structured forecast builder — composes real engine outputs (Prompt 34/38 subset)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.control_fabric.risk_engine import RiskEngine, get_risk_engine
from app.services.explainability.layer import ExplainabilityLayer
from app.services.factor.engine import FactorEngine
from app.services.factor.types import FactorName
from app.services.forecast.engine import ForecastEngine, get_forecast_engine
from app.services.forecast.types import InstrumentForecast, RiskFlag
from app.services.macro.sector_seed import sector_for_symbol
from app.services.regime.types import MarketRegimeLabel
from app.services.scenario.engine import ScenarioEngine
from app.services.scenario.types import PortfolioPosition, PortfolioSnapshot, ScenarioName
from app.utils.helpers import utcnow

HIGH_CONFIDENCE_THRESHOLD = 0.85

_REGIME_RU: dict[str, str] = {
    MarketRegimeLabel.BULLISH_TREND.value: "бычий тренд",
    MarketRegimeLabel.BEARISH_TREND.value: "медвежий тренд",
    MarketRegimeLabel.CHOPPY_RANGE.value: "боковик",
    MarketRegimeLabel.HIGH_VOLATILITY_SHOCK.value: "шок волатильности",
    MarketRegimeLabel.LIQUIDITY_DROUGHT.value: "дефицит ликвидности",
    MarketRegimeLabel.MACRO_UNCERTAINTY.value: "макро-неопределённость",
}

_FACTOR_RU: dict[str, str] = {
    FactorName.MARKET_BETA.value: "рыночная бетта",
    FactorName.SECTOR_FACTOR.value: "секторный фактор",
    FactorName.MOMENTUM.value: "моментум",
    FactorName.VOLATILITY_FACTOR.value: "волатильность",
    FactorName.RATES_SENSITIVITY.value: "чувствительность к ставкам",
    FactorName.MACRO_SHOCK_SENSITIVITY.value: "макро-шок",
}


def _pct(probability: float) -> float:
    return round(max(0.0, min(1.0, probability)) * 100.0, 1)


def _maybe_high_confidence(probability: float) -> float | None:
    if probability >= HIGH_CONFIDENCE_THRESHOLD:
        return round(probability, 4)
    return None


class DailyForecastBuilder:
    """Build structured daily forecast sections from live engine outputs."""

    def __init__(
        self,
        *,
        forecast_engine: ForecastEngine | None = None,
        factor_engine: FactorEngine | None = None,
        risk_engine: RiskEngine | None = None,
        scenario_engine: ScenarioEngine | None = None,
    ) -> None:
        self._forecast_engine = forecast_engine or get_forecast_engine()
        self._factor_engine = factor_engine or FactorEngine()
        self._risk_engine = risk_engine or get_risk_engine()
        self._scenario_engine = scenario_engine or ScenarioEngine()

    async def build(
        self,
        db: AsyncSession,
        *,
        instrument_id: int,
        symbol: str,
        as_of: datetime | None = None,
        skip_explain: bool = False,
    ) -> dict[str, Any]:
        as_of = as_of or utcnow()
        forecast = await self._forecast_engine.forecast_instrument(db, instrument_id, as_of=as_of)
        if forecast is None:
            raise ValueError(f"Insufficient market data for {symbol}")

        snapshot = None
        if not skip_explain:
            explain = ExplainabilityLayer(forecast_engine=self._forecast_engine)
            snapshot = await explain.explain_for_instrument(db, instrument_id)
        try:
            factor_rows = await self._factor_engine.estimate_for_instrument(
                db,
                instrument_id=instrument_id,
                as_of=as_of,
            )
        except ValueError:
            # Point-in-time backfill: missing aligned factor history should not
            # abort the whole snapshot (direction still comes from hierarchy).
            factor_rows = []
        latest_factors = _latest_factor_map(factor_rows)
        sector = (sector_for_symbol(symbol) or ("unknown", "unknown"))[0]

        scenario_probs = await self._scenario_probabilities(db, instrument_id, latest_factors)
        market_outlook = _build_market_outlook(forecast, symbol=symbol)
        sector_opportunities, sector_risks = _build_sector_views(
            symbol,
            sector,
            latest_factors,
            forecast,
        )
        regime_forecast = _build_regime_forecast(forecast)
        tail_risk_events = _build_tail_risk_events(forecast, scenario_probs)
        actionable_summary = _build_actionable_summary(
            symbol,
            forecast,
            latest_factors,
            snapshot.source_metrics if snapshot else {},
        )
        high_confidence = _collect_high_confidence(
            market_outlook,
            sector_opportunities,
            sector_risks,
            tail_risk_events,
            regime_forecast,
        )

        return {
            "symbol": symbol.upper(),
            "instrument_id": instrument_id,
            "as_of": as_of.isoformat(),
            "market_outlook": market_outlook,
            "sector_opportunities": sector_opportunities,
            "sector_risks": sector_risks,
            "regime_forecast": regime_forecast,
            "tail_risk_events": tail_risk_events,
            "actionable_summary": actionable_summary,
            "high_confidence_predictions": high_confidence,
            "engines_used": [
                "RegimeEngine",
                "FactorEngine",
                "ForecastEngine",
                "RiskEngine",
                "ScenarioEngine",
            ],
            "probability_map": forecast.signals.as_dict(),
            "composite_risk_score": forecast.composite_risk_score,
            "confidence": forecast.confidence,
            "risk_flags": list(forecast.risk_flags),
            "factor_exposures": latest_factors,
            "source_metrics": snapshot.source_metrics if snapshot else {},
        }

    async def _scenario_probabilities(
        self,
        db: AsyncSession,
        instrument_id: int,
        factor_exposures: dict[str, float],
    ) -> dict[str, float]:
        from sqlalchemy import select

        from app.domain.market_data import MarketOhlcvORM
        from app.services.regime.features import prices_to_returns

        stmt = (
            select(MarketOhlcvORM)
            .where(
                MarketOhlcvORM.instrument_id == instrument_id,
                MarketOhlcvORM.timeframe == "1d",
            )
            .order_by(MarketOhlcvORM.time.desc())
            .limit(120)
        )
        rows = list((await db.execute(stmt)).scalars().all())
        rows.reverse()
        if len(rows) < 10:
            return {}

        returns = prices_to_returns([float(row.close) for row in rows if row.close])
        if len(returns) < 5:
            return {}

        factor_map: dict[FactorName, float] = {}
        for key, value in factor_exposures.items():
            try:
                factor_map[FactorName(key)] = value
            except ValueError:
                continue

        portfolio = PortfolioSnapshot(
            positions=(PortfolioPosition(instrument_id=instrument_id, sleeve_id="default", weight=1.0),),
            factor_exposures={instrument_id: factor_map},
            returns_by_instrument={instrument_id: returns},
        )

        probs: dict[str, float] = {}
        for scenario in (ScenarioName.RATE_SHOCK, ScenarioName.VIX_SPIKE, ScenarioName.BAD_CPI_SURPRISE):
            try:
                result = self._scenario_engine.run(scenario, portfolio)
                impact = abs(result.estimated_pnl_impact)
                probs[scenario.value] = min(1.0, impact * 4.0 + forecast_tail_boost(result.portfolio_variance_delta))
            except Exception:
                continue
        return probs


def forecast_tail_boost(variance_delta: float) -> float:
    return min(0.5, max(0.0, variance_delta) * 2.0)


def _latest_factor_map(rows) -> dict[str, float]:
    if not rows:
        return {}
    latest_time = max(row.time for row in rows)
    return {
        row.factor_name.value: round(float(row.beta), 4)
        for row in rows
        if row.time == latest_time
    }


def _build_market_outlook(forecast: InstrumentForecast, *, symbol: str = "") -> list[dict[str, Any]]:
    bullish = forecast.regime_distribution.get(MarketRegimeLabel.BULLISH_TREND.value, 0.0)
    bearish = forecast.regime_distribution.get(MarketRegimeLabel.BEARISH_TREND.value, 0.0)
    neutral = max(
        0.0,
        1.0
        - bullish
        - bearish
        - forecast.regime_distribution.get(MarketRegimeLabel.HIGH_VOLATILITY_SHOCK.value, 0.0),
    )
    sym = symbol.upper() if symbol else "инструмент"
    mom = forecast.signals.short_term_momentum
    vol = float(getattr(forecast.signals, "volatility_expansion_probability", 0.0) or 0.0)
    scenarios = [
        {
            "scenario": "bullish",
            "label_ru": f"{sym}: благоприятный сценарий",
            "probability": round(bullish, 4),
            "probability_pct": _pct(bullish),
            "engine": "RegimeEngine",
            "high_confidence": _maybe_high_confidence(bullish),
            "what_happens": (
                f"Импульс {sym} поддерживает бычий режим (сила {mom:.0%}, ForecastEngine)."
            ),
        },
        {
            "scenario": "bearish",
            "label_ru": f"{sym}: негативный сценарий",
            "probability": round(bearish, 4),
            "probability_pct": _pct(bearish),
            "engine": "RegimeEngine",
            "high_confidence": _maybe_high_confidence(bearish),
            "what_happens": (
                f"Слабый/отрицательный импульс и риск-метрики указывают на давление на {sym}."
            ),
        },
        {
            "scenario": "neutral",
            "label_ru": f"{sym}: нейтральный / боковой",
            "probability": round(neutral, 4),
            "probability_pct": _pct(neutral),
            "engine": "ForecastEngine",
            "high_confidence": _maybe_high_confidence(neutral),
            "what_happens": (
                f"Боковик: импульс {mom:.0%}, волатильность ~{vol:.0%} — без явного тренда по {sym}."
            ),
        },
    ]
    return sorted(scenarios, key=lambda item: item["probability"], reverse=True)


def _build_sector_views(
    symbol: str,
    sector: str,
    factors: dict[str, float],
    forecast: InstrumentForecast,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    opportunities: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []

    momentum = factors.get(FactorName.MOMENTUM.value, 0.0)
    sector_beta = factors.get(FactorName.SECTOR_FACTOR.value, 0.0)
    vol_factor = factors.get(FactorName.VOLATILITY_FACTOR.value, 0.0)

    if momentum > 0.05:
        prob = min(1.0, 0.55 + momentum)
        opportunities.append(
            {
                "label": f"{sector} momentum strength",
                "label_ru": f"Сектор {sector}: положительный моментум",
                "probability": round(prob, 4),
                "probability_pct": _pct(prob),
                "engine": "FactorEngine",
                "symbol": symbol,
                "high_confidence": _maybe_high_confidence(prob),
            }
        )
    if sector_beta > 0.1 and forecast.dominant_regime == MarketRegimeLabel.BULLISH_TREND.value:
        prob = min(1.0, forecast.confidence * 0.9)
        opportunities.append(
            {
                "label": f"{sector} aligned with bullish regime",
                "label_ru": f"Сектор {sector} совпадает с бычьим режимом",
                "probability": round(prob, 4),
                "probability_pct": _pct(prob),
                "engine": "RegimeEngine",
                "symbol": symbol,
                "high_confidence": _maybe_high_confidence(prob),
            }
        )

    if vol_factor > 0.15 or RiskFlag.VOLATILITY_EXPANSION.value in forecast.risk_flags:
        prob = min(1.0, forecast.signals.volatility_expansion_probability + 0.1)
        risks.append(
            {
                "label": f"{sector} volatility expansion",
                "label_ru": f"Сектор {sector}: риск расширения волатильности",
                "probability": round(prob, 4),
                "probability_pct": _pct(prob),
                "engine": "ForecastEngine",
                "symbol": symbol,
                "high_confidence": _maybe_high_confidence(prob),
            }
        )
    if sector_beta < -0.05:
        prob = min(1.0, 0.5 + abs(sector_beta))
        risks.append(
            {
                "label": f"{sector} relative weakness",
                "label_ru": f"Сектор {sector}: относительная слабость",
                "probability": round(prob, 4),
                "probability_pct": _pct(prob),
                "engine": "FactorEngine",
                "symbol": symbol,
                "high_confidence": _maybe_high_confidence(prob),
            }
        )

    return opportunities, risks


def _build_regime_forecast(forecast: InstrumentForecast) -> dict[str, Any]:
    distribution = [
        {
            "regime": regime,
            "label_ru": _REGIME_RU.get(regime, regime),
            "probability": round(prob, 4),
            "probability_pct": _pct(prob),
            "engine": "RegimeEngine",
            "high_confidence": _maybe_high_confidence(prob),
        }
        for regime, prob in sorted(
            forecast.regime_distribution.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    ]
    return {
        "dominant_regime": forecast.dominant_regime,
        "dominant_regime_ru": _REGIME_RU.get(forecast.dominant_regime, forecast.dominant_regime),
        "confidence": round(forecast.confidence, 4),
        "distribution": distribution,
        "engine": "RegimeEngine",
    }


def _build_tail_risk_events(
    forecast: InstrumentForecast,
    scenario_probs: dict[str, float],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    tail_prob = min(1.0, forecast.signals.tail_risk_score * 0.85 + 0.1)
    if forecast.signals.tail_risk_score >= 0.35:
        events.append(
            {
                "label": "Tail risk elevated",
                "label_ru": "Повышенный хвостовой риск",
                "probability": round(tail_prob, 4),
                "probability_pct": _pct(tail_prob),
                "engine": "RiskEngine",
                "high_confidence": _maybe_high_confidence(tail_prob),
            }
        )
    if forecast.signals.event_impact_score >= 0.3:
        prob = min(1.0, forecast.signals.event_impact_score + 0.15)
        events.append(
            {
                "label": "News/event shock window",
                "label_ru": "Окно новостного/событийного риска",
                "probability": round(prob, 4),
                "probability_pct": _pct(prob),
                "engine": "ForecastEngine",
                "high_confidence": _maybe_high_confidence(prob),
            }
        )
    for scenario, prob in scenario_probs.items():
        if prob < 0.25:
            continue
        label_ru = {
            ScenarioName.RATE_SHOCK.value: "Шок процентных ставок",
            ScenarioName.VIX_SPIKE.value: "Скачок волатильности (VIX)",
            ScenarioName.BAD_CPI_SURPRISE.value: "Негативный сюрприз по инфляции",
        }.get(scenario, scenario)
        events.append(
            {
                "label": scenario,
                "label_ru": label_ru,
                "probability": round(prob, 4),
                "probability_pct": _pct(prob),
                "engine": "ScenarioEngine",
                "high_confidence": _maybe_high_confidence(prob),
            }
        )
    return sorted(events, key=lambda item: item["probability"], reverse=True)


def _build_actionable_summary(
    symbol: str,
    forecast: InstrumentForecast,
    factors: dict[str, float],
    source_metrics: dict[str, Any],
) -> list[str]:
    summary: list[str] = []
    regime_ru = _REGIME_RU.get(forecast.dominant_regime, forecast.dominant_regime)
    summary.append(
        f"{symbol}: доминирующий режим — {regime_ru} "
        f"(уверенность {int(forecast.confidence * 100)}%, RegimeEngine)."
    )

    if forecast.signals.momentum_direction.value == "bullish" and forecast.signals.short_term_momentum > 0.4:
        summary.append(
            f"Краткосрочный импульс положительный ({int(forecast.signals.short_term_momentum * 100)}%, ForecastEngine)."
        )
    elif forecast.signals.momentum_direction.value == "bearish" and forecast.signals.short_term_momentum > 0.4:
        summary.append(
            f"Краткосрочный импульс отрицательный ({int(forecast.signals.short_term_momentum * 100)}%, ForecastEngine)."
        )

    dominant_factor = max(factors.items(), key=lambda item: abs(item[1]), default=(None, 0.0))
    if dominant_factor[0] and abs(dominant_factor[1]) >= 0.1:
        factor_ru = _FACTOR_RU.get(dominant_factor[0], dominant_factor[0])
        summary.append(
            f"Главный фактор риска/доходности: {factor_ru} (β={dominant_factor[1]:+.2f}, FactorEngine)."
        )

    risk_metrics = source_metrics.get("risk", {})
    if risk_metrics.get("tail_risk_score", 0) >= 0.5:
        summary.append("Хвостовой риск выше нормы — уменьшайте размер позиции (RiskEngine).")

    if forecast.composite_risk_score >= 0.65:
        summary.append("Композитный риск высокий — предпочтительно выжидание (ForecastEngine).")
    elif forecast.composite_risk_score <= 0.35 and forecast.confidence >= 0.6:
        summary.append("Риск умеренный при достаточной уверенности модели — можно рассматривать вход с лимитом размера.")

    return summary


def _collect_high_confidence(*sections) -> list[dict[str, Any]]:
    high: list[dict[str, Any]] = []
    for section in sections:
        if isinstance(section, dict):
            items = section.get("distribution", [])
        elif isinstance(section, list):
            items = section
        else:
            continue
        for item in items:
            hc = item.get("high_confidence")
            if hc is not None:
                label = item.get("label") or item.get("scenario") or item.get("regime") or item.get("engine")
                if not label:
                    continue
                high.append(
                    {
                        **item,
                        "label": str(label),
                        "label_ru": str(item.get("label_ru") or label),
                        "probability": hc,
                    }
                )
    return sorted(high, key=lambda item: item["probability"], reverse=True)


_builder = DailyForecastBuilder()


def get_daily_forecast_builder() -> DailyForecastBuilder:
    return _builder
