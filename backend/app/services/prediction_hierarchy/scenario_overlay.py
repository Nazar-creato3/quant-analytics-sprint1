"""Four-layer forecast overlays — global macro, sector, instrument, portfolio."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from app.services.prediction_hierarchy.forecast_output import _narrative_scenario_probabilities
from app.services.prediction_hierarchy.types import (
    ForecastOutput,
    GlobalRegimeLabel,
    GlobalRegimeResult,
    PortfolioContext,
    SectorRegimeContext,
    SectorRotationScore,
)
from app.services.quant_math import historical_volatility
from app.services.regime.features import prices_to_returns


_ARCHETYPE_KEYS = ("pessimistic", "realistic", "optimistic", "classic")


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _normalize_weights(weights: Mapping[str, float]) -> dict[str, float]:
    total = sum(float(weights.get(key, 0.0)) for key in _ARCHETYPE_KEYS)
    if total <= 0.0:
        return {key: 0.25 for key in _ARCHETYPE_KEYS}
    return {key: round(float(weights.get(key, 0.0)) / total, 4) for key in _ARCHETYPE_KEYS}


def _macro_regime_distribution(global_result: GlobalRegimeResult) -> dict[str, float]:
    distribution = global_result.distribution
    return {
        "bullish_trend": float(distribution.get(GlobalRegimeLabel.RISK_ON.value, 0.0)),
        "bearish_trend": float(distribution.get(GlobalRegimeLabel.RISK_OFF.value, 0.0)),
        "choppy_range": float(distribution.get(GlobalRegimeLabel.MACRO_UNCERTAINTY.value, 0.0)),
        "high_volatility_shock": float(
            distribution.get(GlobalRegimeLabel.CREDIT_STRESS.value, 0.0)
            + distribution.get(GlobalRegimeLabel.INFLATION_SHOCK_REGIME.value, 0.0)
        ),
    }


@dataclass(frozen=True, slots=True)
class GlobalMacroSnapshot:
    """Shared macro bundle — identical for all tickers at a given refresh instant."""

    indicators: Mapping[str, float]
    global_regime: GlobalRegimeResult
    loaded_at: str
    source_timestamps: Mapping[str, str] = field(default_factory=dict)
    cache_key: str = "macro:snapshot:global"
    is_stale: bool = False
    stale_reason: str = ""

    @property
    def vol_proxy(self) -> float:
        vix = self.indicators.get("vix")
        if vix is None:
            return 0.35
        return min(1.0, float(vix) / 40.0)

    @property
    def tail_risk(self) -> float:
        return float(
            self.global_regime.distribution.get(GlobalRegimeLabel.CREDIT_STRESS.value, 0.0)
        )

    @property
    def composite_risk(self) -> float:
        return float(
            self.global_regime.distribution.get(GlobalRegimeLabel.RISK_OFF.value, 0.0)
        )

    @property
    def regime_distribution(self) -> dict[str, float]:
        return _macro_regime_distribution(self.global_regime)

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": "global_macro",
            "indicators": dict(self.indicators),
            "dominant_regime": self.global_regime.dominant_regime,
            "confidence": self.global_regime.confidence,
            "distribution": dict(self.global_regime.distribution),
            "loaded_at": self.loaded_at,
            "source_timestamps": dict(self.source_timestamps),
            "cache_key": self.cache_key,
            "is_stale": self.is_stale,
            "stale_reason": self.stale_reason,
        }


@dataclass(frozen=True, slots=True)
class SectorOverlay:
    """Sector-specific context for the instrument's mapped sector."""

    sector: str
    rotation: SectorRotationScore
    sector_momentum: float
    dominant_sector_regime: str
    as_of: str
    rank: int = 0

    @property
    def momentum_bp(self) -> float:
        """Relative strength in basis points (return delta × 10 000)."""
        return round(self.rotation.composite_score * 10_000.0, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": "sector",
            "sector": self.sector,
            "dominant_sector_regime": self.dominant_sector_regime,
            "sector_momentum": round(self.sector_momentum, 6),
            "rotation_flag": self.rotation.rotation_flag.value,
            "composite_score": self.rotation.composite_score,
            "momentum_bp": self.momentum_bp,
            "score_1w": self.rotation.score_1w,
            "score_1m": self.rotation.score_1m,
            "score_3m": self.rotation.score_3m,
            "rank": self.rank or self.rotation.rank,
            "as_of": self.as_of,
        }


@dataclass(frozen=True, slots=True)
class InstrumentOverlay:
    """Ticker-specific features driving scenario shifts."""

    symbol: str
    momentum: float
    vol_expansion: float
    tail_risk: float
    composite_risk: float
    realized_vol: float
    liquidity_score: float
    relative_strength: float
    regime_distribution: Mapping[str, float]
    as_of: str
    expected_move: float = 0.0
    volatility_regime: str = "moderate"

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": "instrument",
            "symbol": self.symbol,
            "momentum": round(self.momentum, 4),
            "vol_expansion": round(self.vol_expansion, 4),
            "tail_risk": round(self.tail_risk, 4),
            "composite_risk": round(self.composite_risk, 4),
            "realized_vol": round(self.realized_vol, 6),
            "liquidity_score": round(self.liquidity_score, 4),
            "relative_strength": round(self.relative_strength, 4),
            "expected_move": round(self.expected_move, 6),
            "volatility_regime": self.volatility_regime,
            "regime_distribution": dict(self.regime_distribution),
            "as_of": self.as_of,
        }


@dataclass(frozen=True, slots=True)
class PortfolioOverlay:
    """User portfolio exposure to the symbol — optional."""

    has_exposure: bool
    exposure_weight: float
    marginal_delta_var: float
    portfolio_risk_score: float
    as_of: str
    recommendation: str = "wait"

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": "portfolio",
            "has_exposure": self.has_exposure,
            "exposure_weight": round(self.exposure_weight, 4),
            "marginal_delta_var": round(self.marginal_delta_var, 6),
            "portfolio_risk_score": round(self.portfolio_risk_score, 4),
            "recommendation": self.recommendation,
            "as_of": self.as_of,
        }


@dataclass(frozen=True, slots=True)
class ScenarioBreakdown:
    """Per-layer contribution weights to the final scenario mix."""

    macro_score: float
    sector_score: float
    symbol_score: float
    portfolio_score: float

    def to_dict(self) -> dict[str, float]:
        return {
            "macro_score": self.macro_score,
            "sector_score": self.sector_score,
            "symbol_score": self.symbol_score,
            "portfolio_score": self.portfolio_score,
        }


@dataclass(frozen=True, slots=True)
class ForecastOverlayBundle:
    global_macro: GlobalMacroSnapshot
    sector: SectorOverlay | None
    instrument: InstrumentOverlay
    portfolio: PortfolioOverlay | None
    scenario_probabilities: dict[str, float]
    breakdown: ScenarioBreakdown
    audit: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "global_macro": self.global_macro.to_dict(),
            "sector": self.sector.to_dict() if self.sector else None,
            "instrument": self.instrument.to_dict(),
            "portfolio": self.portfolio.to_dict() if self.portfolio else None,
            "scenario_probabilities": dict(self.scenario_probabilities),
            "breakdown": self.breakdown.to_dict(),
            "audit": self.audit,
        }


def _layer_magnitude(delta: Mapping[str, float]) -> float:
    return sum(abs(float(delta.get(key, 0.0))) for key in _ARCHETYPE_KEYS)


def compute_layered_scenario_probabilities(
    *,
    macro: GlobalMacroSnapshot,
    sector: SectorOverlay | None,
    instrument: InstrumentOverlay,
    portfolio: PortfolioOverlay | None = None,
) -> tuple[dict[str, float], ScenarioBreakdown, dict[str, Any]]:
    """Combine four overlay layers — macro base plus sector/instrument/portfolio shifts."""
    macro_base = _narrative_scenario_probabilities(
        vol=macro.vol_proxy,
        momentum=0.5,
        tail_risk=macro.tail_risk,
        composite_risk=macro.composite_risk,
        regime_distribution=macro.regime_distribution,
    )

    sector_signal = 0.0
    sector_strength = 0.0
    if sector is not None:
        sector_signal = _clamp(sector.sector_momentum * 12.0 + sector.rotation.composite_score * 40.0)
        sector_strength = _clamp(sector.rotation.composite_score * 60.0 + sector.sector_momentum * 8.0)

    sector_delta = {
        "pessimistic": max(0.0, -sector_signal) * 0.14 + max(0.0, -sector_strength) * 0.06,
        "realistic": (1.0 - abs(sector_signal)) * 0.04,
        "optimistic": max(0.0, sector_signal) * 0.14 + max(0.0, sector_strength) * 0.06,
        "classic": abs(sector_signal) * 0.03,
    }

    inst_momentum = instrument.momentum
    bearish_pressure = max(0.0, 0.5 - inst_momentum) * 2.0
    bullish_pressure = max(0.0, inst_momentum - 0.5) * 2.0

    instrument_delta = {
        "pessimistic": (
            instrument.vol_expansion * 0.18
            + instrument.tail_risk * 0.16
            + bearish_pressure * 0.14
            + max(0.0, -instrument.relative_strength) * 0.08
        ),
        "realistic": (
            (1.0 - abs(inst_momentum - 0.5) * 2.0) * 0.12
            + (1.0 - instrument.vol_expansion) * 0.04
        ),
        "optimistic": (
            (1.0 - instrument.vol_expansion) * 0.14
            + bullish_pressure * 0.16
            + max(0.0, instrument.relative_strength) * 0.08
            + max(0.0, 1.0 - instrument.composite_risk) * 0.04
        ),
        "classic": (
            float(instrument.regime_distribution.get("choppy_range", 0.0)) * 0.12
            + (1.0 - abs(bullish_pressure - bearish_pressure)) * 0.05
        ),
    }

    portfolio_delta = {key: 0.0 for key in _ARCHETYPE_KEYS}
    if portfolio is not None and portfolio.has_exposure:
        stress = _clamp(portfolio.portfolio_risk_score + portfolio.marginal_delta_var * 2.0)
        portfolio_delta = {
            "pessimistic": stress * 0.10 + max(0.0, portfolio.exposure_weight - 0.05) * 0.06,
            "realistic": (1.0 - stress) * 0.04,
            "optimistic": max(0.0, 0.15 - stress) * 0.06,
            "classic": stress * 0.03,
        }

    combined = {
        key: macro_base[key] + sector_delta[key] + instrument_delta[key] + portfolio_delta[key]
        for key in _ARCHETYPE_KEYS
    }
    final_probs = _normalize_weights(combined)

    macro_mag = _layer_magnitude(macro_base)
    sector_mag = _layer_magnitude(sector_delta)
    inst_mag = _layer_magnitude(instrument_delta)
    port_mag = _layer_magnitude(portfolio_delta)
    total_mag = macro_mag + sector_mag + inst_mag + port_mag
    if total_mag <= 0.0:
        breakdown = ScenarioBreakdown(0.25, 0.25, 0.25, 0.25)
    else:
        breakdown = ScenarioBreakdown(
            macro_score=round(macro_mag / total_mag, 4),
            sector_score=round(sector_mag / total_mag, 4),
            symbol_score=round(inst_mag / total_mag, 4),
            portfolio_score=round(port_mag / total_mag, 4),
        )

    audit = {
        "macro_base": macro_base,
        "sector_delta": sector_delta,
        "instrument_delta": instrument_delta,
        "portfolio_delta": portfolio_delta,
        "combined_pre_normalize": combined,
        "final": final_probs,
    }
    return final_probs, breakdown, audit


def _volatility_regime_label(vol_expansion: float, realized_vol: float) -> str:
    score = max(vol_expansion, min(1.0, realized_vol * 8.0))
    if score >= 0.45:
        return "elevated"
    if score >= 0.20:
        return "moderate"
    return "contained"


def build_forecast_overlays(
    *,
    hierarchy: ForecastOutput,
    macro_snapshot: GlobalMacroSnapshot,
    prices: list[float] | None = None,
    sector_rank: int = 0,
    portfolio_context: PortfolioContext | None = None,
) -> ForecastOverlayBundle:
    """Assemble overlay bundle from hierarchy output and macro snapshot."""
    sector_overlay: SectorOverlay | None = None
    if hierarchy.sector_regime is not None:
        sector_ctx = hierarchy.sector_regime
        sector_overlay = SectorOverlay(
            sector=sector_ctx.sector,
            rotation=sector_ctx.rotation,
            sector_momentum=sector_ctx.sector_momentum,
            dominant_sector_regime=sector_ctx.regime.dominant_regime,
            as_of=hierarchy.as_of,
            rank=sector_rank or sector_ctx.rotation.rank,
        )

    metrics = hierarchy.risk_forecast.instrument_metrics
    returns = prices_to_returns(prices) if prices else []
    realized_vol = historical_volatility(returns) if len(returns) >= 2 else 0.0
    rel_strength = 0.0
    if sector_overlay is not None:
        rel_strength = _clamp(sector_overlay.sector_momentum * 10.0 + (hierarchy.point_forecast.momentum_score - 0.5))

    expected_move = (hierarchy.point_forecast.momentum_score - 0.5) * 0.08
    vol_regime = _volatility_regime_label(
        float(metrics.get("volatility_expansion_probability", 0.0)),
        realized_vol,
    )

    instrument_overlay = InstrumentOverlay(
        symbol=hierarchy.symbol,
        momentum=hierarchy.point_forecast.momentum_score,
        vol_expansion=float(metrics.get("volatility_expansion_probability", 0.0)),
        tail_risk=float(metrics.get("tail_risk_score", 0.0)),
        composite_risk=float(metrics.get("composite_risk_score", 0.0)),
        realized_vol=realized_vol,
        liquidity_score=float(metrics.get("liquidity_risk_score", 0.0)),
        relative_strength=rel_strength,
        regime_distribution=hierarchy.sector_regime.regime.distribution if hierarchy.sector_regime else {},
        as_of=hierarchy.as_of,
        expected_move=expected_move,
        volatility_regime=vol_regime,
    )

    portfolio_overlay: PortfolioOverlay | None = None
    marginal = hierarchy.risk_forecast.marginal_impact
    if portfolio_context and portfolio_context.positions:
        target_weight = 0.0
        for position in portfolio_context.positions:
            if getattr(position, "instrument_id", None) == hierarchy.instrument_id:
                target_weight = float(getattr(position, "weight", 0.0))
                break
        portfolio_overlay = PortfolioOverlay(
            has_exposure=target_weight > 0.0,
            exposure_weight=target_weight,
            marginal_delta_var=marginal.delta_var if marginal else 0.0,
            portfolio_risk_score=float(metrics.get("composite_risk_score", 0.0)),
            as_of=hierarchy.as_of,
            recommendation=hierarchy.action_forecast.recommendation.value,
        )

    probs, breakdown, audit = compute_layered_scenario_probabilities(
        macro=macro_snapshot,
        sector=sector_overlay,
        instrument=instrument_overlay,
        portfolio=portfolio_overlay,
    )

    return ForecastOverlayBundle(
        global_macro=macro_snapshot,
        sector=sector_overlay,
        instrument=instrument_overlay,
        portfolio=portfolio_overlay,
        scenario_probabilities=probs,
        breakdown=breakdown,
        audit=audit,
    )


# Plain-language Russian labels for user-facing narrative (no raw enum keys).
GLOBAL_REGIME_RU: dict[str, str] = {
    GlobalRegimeLabel.RISK_ON.value: "благоприятный фон для рисковых активов",
    GlobalRegimeLabel.RISK_OFF.value: "осторожный фон с уклоном в защитные активы",
    GlobalRegimeLabel.MACRO_UNCERTAINTY.value: "повышенная макро-неопределённость",
    GlobalRegimeLabel.CREDIT_STRESS.value: "стресс на кредитном рынке",
    GlobalRegimeLabel.INFLATION_SHOCK_REGIME.value: "инфляционный шок",
}

SECTOR_REGIME_RU: dict[str, str] = {
    "bullish_trend": "устойчивый восходящий тренд",
    "bearish_trend": "устойчивый нисходящий тренд",
    "choppy_range": "боковое движение без чёткого тренда",
    "high_volatility_shock": "резкий скачок волатильности",
    "market_aggregate": "сводный рыночный режим",
}

VOLATILITY_REGIME_RU: dict[str, str] = {
    "contained": "сдержанная, рынок относительно спокоен",
    "moderate": "умеренная, колебания в пределах нормы",
    "elevated": "повышенная, возможны резкие движения",
}

RISK_ACTION_RU: dict[str, str] = {
    "wait": "выжидать и не спешить с решением",
    "reduce_size": "уменьшить размер позиции",
    "hedge": "защитить портфель хеджем",
    "hold": "удерживать текущую позицию",
    "enter_small_size": "войти небольшим объёмом",
    "enter_normal_size": "войти стандартным объёмом",
    "avoid": "воздержаться от сделки",
}

SECTOR_NAME_RU: dict[str, str] = {
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

ROTATION_FLAG_RU: dict[str, str] = {
    "sectors_strengthening": "секторы набирают силу",
    "sectors_weakening": "секторы ослабевают",
    "rotation_in_progress": "идёт ротация между секторами",
    "neutral": "нейтральная динамика секторов",
}


def translate_global_regime(key: str) -> str:
    return GLOBAL_REGIME_RU.get(key, key.replace("_", " "))


def translate_sector_regime(key: str) -> str:
    return SECTOR_REGIME_RU.get(key, key.replace("_", " "))


def translate_volatility_regime(key: str) -> str:
    return VOLATILITY_REGIME_RU.get(key, key.replace("_", " "))


def translate_risk_action(key: str) -> str:
    return RISK_ACTION_RU.get(key, key.replace("_", " "))


def translate_sector_name(key: str) -> str:
    return SECTOR_NAME_RU.get(key, key.replace("_", " "))


def translate_rotation_flag(key: str) -> str:
    return ROTATION_FLAG_RU.get(key, key.replace("_", " "))


def build_global_macro_snapshot(
    *,
    indicators: Mapping[str, float],
    global_result: GlobalRegimeResult,
    loaded_at: str | None = None,
    source_timestamps: Mapping[str, str] | None = None,
    is_stale: bool = False,
    stale_reason: str = "",
) -> GlobalMacroSnapshot:
    now = loaded_at or datetime.now(timezone.utc).isoformat()
    return GlobalMacroSnapshot(
        indicators=dict(indicators),
        global_regime=global_result,
        loaded_at=now,
        source_timestamps=dict(source_timestamps or {}),
        is_stale=is_stale,
        stale_reason=stale_reason,
    )
