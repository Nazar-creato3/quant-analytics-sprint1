"""Signal presentation metadata for maneuvers (spec A.3, A.6)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

import pandas as pd

from app.core.config import settings
from app.services.market_analysis.shap_explainer import compute_shap_top_factors
from app.services.macro.sector_seed import sector_for_symbol
from app.services.ml.features import compute_features
from app.services.regime.engine import RegimeEngine

if TYPE_CHECKING:
    from app.services.risk.maneuver_generator import ManeuverCandidate

# Historical model reliability by simple regime label (backtest-derived defaults).
_REGIME_RELIABILITY: dict[str, float] = {
    "trending_up": 0.68,
    "trending_down": 0.62,
    "range_bound": 0.54,
    "high_volatility": 0.48,
    "bull": 0.66,
    "bear": 0.58,
    "sideways": 0.55,
    "volatile": 0.50,
    "unknown": 0.52,
}

_FEATURE_LABELS_RU: dict[str, str] = {
    "rsi_14": "перекупленность или перепроданность бумаги",
    "macd_bullish": "короткий импульс против более длинного",
    "roc_5": "движение за последнюю неделю",
    "roc_20": "движение за последний месяц",
    "price_vs_sma20": "цена относительно средней за месяц",
    "volatility_20d": "волатильность цены за 20 дней",
    "volume_ratio": "объём торгов относительно обычного",
    "bb_position": "где цена внутри обычного коридора",
    "atr_pct": "типичный дневной размах цены",
}


@dataclass
class ManeuverPresentation:
    regime_label: str = "unknown"
    regime_context: str = ""
    regime_reliability: float = 0.5
    suggested_position_pct: float = 0.0
    confidence_low: float = 0.0
    confidence_high: float = 0.0
    key_drivers: list[dict[str, Any]] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    sector: str = "unknown"
    portfolio_overlay: dict[str, Any] = field(default_factory=dict)
    adx_value: float | None = None
    suppress_trend_signal: bool = False
    why_this_trade: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime_label": self.regime_label,
            "regime_context": self.regime_context,
            "regime_reliability": round(self.regime_reliability, 4),
            "suggested_position_pct": round(self.suggested_position_pct, 4),
            "confidence_interval": [
                round(self.confidence_low, 4),
                round(self.confidence_high, 4),
            ],
            "key_drivers": self.key_drivers,
            "risk_flags": self.risk_flags,
            "sector": self.sector,
            "portfolio_overlay": self.portfolio_overlay,
            "adx_value": self.adx_value,
            "suppress_trend_signal": self.suppress_trend_signal,
            "why_this_trade": self.why_this_trade,
        }


def _compute_adx(df: pd.DataFrame, period: int = 14) -> float | None:
    if len(df) < period + 2:
        return None
    high = df["high"]
    low = df["low"]
    close = df["close"]
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / (atr + 1e-10))
    minus_di = 100 * (minus_dm.rolling(period).mean() / (atr + 1e-10))
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10) * 100
    adx = dx.rolling(period).mean()
    val = adx.iloc[-1]
    return float(val) if pd.notna(val) else None


def _hmm_regime_label(df: pd.DataFrame) -> tuple[str, float]:
    """Classify regime via HMM engine when enough bars exist."""
    if len(df) < 60:
        return "unknown", 0.5
    try:
        prices = [float(v) for v in df["close"].tolist()]
        volumes = [float(v) for v in df["volume"].tolist()] if "volume" in df.columns else None
        result = RegimeEngine().classify_instrument(prices, volumes)
        label = result.dominant_regime
        return label, float(result.confidence)
    except Exception:
        return "unknown", 0.5


def _regime_context_ru(
    label: str,
    reliability: float,
    adx: float | None,
    suppress_trend: bool,
) -> str:
    names = {
        "trending_up": "рынок скорее растёт",
        "trending_down": "рынок скорее снижается",
        "range_bound": "цена ходит в коридоре без ясного направления",
        "high_volatility": "волатильность рынка выше обычной",
        "bull": "общий фон позитивный",
        "bear": "общий фон негативный",
        "sideways": "общий фон боковой",
        "volatile": "на рынке повышенная волатильность",
        "unknown": "режим рынка пока неясен",
    }
    readable = names.get(label, label.replace("_", " "))
    if reliability >= 0.58:
        rel = "в похожих ситуациях такие идеи чаще срабатывали"
    elif reliability <= 0.52:
        rel = "в похожих ситуациях такие идеи срабатывали реже обычного — размер лучше не раздувать"
    else:
        rel = "успешность таких идей около среднего"
    base = f"Сейчас {readable}. {rel.capitalize()}."
    if adx is not None:
        if adx < 20:
            base += " Сильного направленного хода сейчас мало — идеи «поймать тренд» слабее."
        elif adx > 25:
            base += " Направленное движение выражено — идеи по тренду выглядят естественнее."
    if suppress_trend:
        base += " Поэтому следование за трендом сейчас приглушено."
    return base


def build_maneuver_presentation(
    candidate: "ManeuverCandidate",
    df: pd.DataFrame | None,
    *,
    portfolio_size: float,
    overlay_warnings: list[str] | None = None,
    portfolio_overlay: dict[str, Any] | None = None,
) -> ManeuverPresentation:
    """Build structured presentation payload for a maneuver row."""
    features = candidate.prediction.features_used or {}
    shap_factors, _, _ = compute_shap_top_factors(features, top_n=3)

    key_drivers: list[dict[str, Any]] = []
    if shap_factors:
        for item in shap_factors[:3]:
            key_drivers.append(
                {
                    "feature": item.feature,
                    "contribution": item.contribution,
                    "label": _FEATURE_LABELS_RU.get(item.feature, item.feature),
                }
            )
    else:
        for feat in ("rsi_14", "macd_bullish", "volume_ratio"):
            if feat in features:
                key_drivers.append(
                    {
                        "feature": feat,
                        "contribution": float(features[feat]),
                        "label": _FEATURE_LABELS_RU.get(feat, feat),
                    }
                )

    hmm_label, _ = _hmm_regime_label(df) if df is not None and not df.empty else ("unknown", 0.5)
    simple_regime = candidate.regime or "unknown"

    if settings.PIPELINE_SKIP_HMM_REGIME:
        regime_label = simple_regime
    else:
        regime_label = hmm_label if hmm_label != "unknown" else simple_regime

    adx = _compute_adx(df) if df is not None and not df.empty else None
    suppress_trend = adx is not None and adx < 20 and candidate.strategy_type in {
        "momentum",
        "trend_following",
    }

    reliability = _REGIME_RELIABILITY.get(regime_label, _REGIME_RELIABILITY.get(simple_regime, 0.52))
    if suppress_trend:
        reliability = min(reliability, 0.50)

    conf = float(candidate.prediction.confidence)
    margin = max(0.04, (1.0 - conf) * 0.15)
    position_pct = 0.0
    if portfolio_size > 0 and candidate.risk.position_size_usd > 0:
        position_pct = candidate.risk.position_size_usd / portfolio_size * 100

    sector_mapped = sector_for_symbol(candidate.ticker)
    sector = sector_mapped[0] if sector_mapped else "unknown"

    risk_flags = list(overlay_warnings or [])
    if suppress_trend:
        risk_flags.append("trend_signal_suppressed_range_bound")
    if conf < settings.NO_TRADE_CONFIDENCE_THRESHOLD:
        risk_flags.append("below_confidence_threshold")

    from app.services.risk.human_copy import build_position_rationale

    why = build_position_rationale(
        strategy=str(candidate.strategy_type),
        direction=str(candidate.prediction.direction),
        confidence=conf,
        regime=regime_label,
        features=features,
        is_fallback=bool(candidate.prediction.is_fallback),
        risk_reward=float(candidate.risk.risk_reward_ratio) if candidate.risk.risk_reward_ratio else None,
        sentiment=float(candidate.news_sentiment or 0.0),
    )

    return ManeuverPresentation(
        regime_label=regime_label,
        regime_context=_regime_context_ru(regime_label, reliability, adx, suppress_trend),
        regime_reliability=reliability,
        suggested_position_pct=position_pct,
        confidence_low=max(0.0, conf - margin),
        confidence_high=min(0.99, conf + margin),
        key_drivers=key_drivers[:3],
        risk_flags=risk_flags,
        sector=sector,
        portfolio_overlay=portfolio_overlay or {},
        adx_value=round(adx, 2) if adx is not None else None,
        suppress_trend_signal=suppress_trend,
        why_this_trade=why,
    )
