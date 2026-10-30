"""Adaptive multi-model ensemble forecasting.

Components: ARIMA, momentum, LightGBM (triple-barrier trained), N-BEATS (Darts),
Chronos (optional), regime-specific model. Weights adapt by recent walk-forward
direction accuracy; stacking meta-model can replace the weighted average.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence

import numpy as np

from app.core.logging import get_logger
from app.services.forecast.chronos_component import get_chronos_component
from app.services.forecast.forecast_defaults import SINGLE_NAME_LOW_CONFIDENCE_MESSAGE_RU
from app.services.forecast.gradient_boost_component import get_gradient_boost_component
from app.services.forecast.lob_component import get_lob_component
from app.services.forecast.nbeats_component import get_nbeats_component
from app.services.forecast.regime_models import get_regime_forecast_models
from app.services.forecast.stacking import get_stacking_meta_model
from app.services.regime.engine import RegimeEngine

logger = get_logger(__name__)

MIN_HISTORY_BARS = 30
FORECAST_HORIZON_DAYS = 30
LIVE_ACCURACY_FLOOR = 0.45
AAPL_BEARISH_MOMENTUM_WEIGHT_CAP = 0.35
AAPL_BEARISH_INVERT_MIN_N = 8

MODEL_FAMILY_LABELS: dict[str, tuple[str, str]] = {
    "arima": ("ARIMA", "ARIMA"),
    "momentum": ("Momentum", "Моментум"),
    "lightgbm": ("LightGBM", "LightGBM"),
    "nbeats": ("N-BEATS", "N-BEATS"),
    "chronos": ("Chronos", "Chronos"),
    "regime_model": ("Regime model", "Режимная модель"),
    "lob_microstructure": ("LOB microstructure", "Микроструктура стакана"),
    "confidence_heuristic": (
        "Confidence heuristic",
        "Эвристика по порогу уверенности",
    ),
    "lightgbm_signal": (
        "Confidence heuristic",
        "Эвристика по порогу уверенности",
    ),
}


class ModelFamily(StrEnum):
    ARIMA = "arima"
    MOMENTUM = "momentum"
    LIGHTGBM = "lightgbm"
    NBEATS = "nbeats"
    CHRONOS = "chronos"
    REGIME_MODEL = "regime_model"
    LOB_MICROSTRUCTURE = "lob_microstructure"
    CONFIDENCE_HEURISTIC = "confidence_heuristic"


@dataclass(frozen=True, slots=True)
class ModelForecast:
    family: ModelFamily
    direction: int  # -1, 0, +1
    expected_return: float
    weight: float
    recent_accuracy: float
    available: bool
    note: str = ""


@dataclass(frozen=True, slots=True)
class MomentumDirectionAccuracy:
    """Walk-forward momentum sign accuracy split by predicted direction."""

    bullish_accuracy: float
    bearish_accuracy: float
    bullish_n: int
    bearish_n: int

    def to_dict(self) -> dict[str, object]:
        return {
            "bullish_accuracy": self.bullish_accuracy,
            "bearish_accuracy": self.bearish_accuracy,
            "bullish_n": self.bullish_n,
            "bearish_n": self.bearish_n,
        }


@dataclass(frozen=True, slots=True)
class EnsembleForecast:
    median_return: float
    direction_consensus: int
    models_agreeing: int
    models_total: int
    component_models: tuple[ModelForecast, ...]
    insufficient_history: bool = False
    history_bars: int = 0
    direction_suppressed: bool = False
    suppression_message_ru: str | None = None
    momentum_direction_accuracy: MomentumDirectionAccuracy | None = None
    single_name_low_confidence: bool = False
    default_view: str = "sector_relative"
    engine_overlays: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "median_return": self.median_return,
            "direction_consensus": self.direction_consensus,
            "models_agreeing": self.models_agreeing,
            "models_total": self.models_total,
            "insufficient_history": self.insufficient_history,
            "history_bars": self.history_bars,
            "direction_suppressed": self.direction_suppressed,
            "suppression_message_ru": self.suppression_message_ru,
            "single_name_low_confidence": self.single_name_low_confidence,
            "default_view": self.default_view,
            "momentum_direction_accuracy": (
                self.momentum_direction_accuracy.to_dict()
                if self.momentum_direction_accuracy
                else None
            ),
            "component_models": [
                {
                    "family": m.family.value,
                    "family_label": MODEL_FAMILY_LABELS.get(m.family.value, (m.family.value, m.family.value))[0],
                    "family_label_ru": MODEL_FAMILY_LABELS.get(m.family.value, (m.family.value, m.family.value))[1],
                    "direction": m.direction,
                    "expected_return": m.expected_return,
                    "weight": m.weight,
                    "recent_accuracy": m.recent_accuracy,
                    "available": m.available,
                    "note": m.note,
                }
                for m in self.component_models
            ],
            "engine_overlays": self.engine_overlays,
        }


def _direction_from_return(ret: float, threshold: float = 0.002) -> int:
    if ret > threshold:
        return 1
    if ret < -threshold:
        return -1
    return 0


_MAX_EVAL_POINTS = 24


def _rolling_directional_accuracy(
    prices: Sequence[float],
    predictor_fn,
    *,
    window: int = 20,
    horizon: int = 5,
) -> float:
    """Walk-forward sign-match accuracy for ensemble weighting."""
    if len(prices) < window + horizon + 5:
        return 0.5
    hits = 0
    total = 0
    # Evenly spaced evaluation points (at most _MAX_EVAL_POINTS): each point refits the model,
    # and with statsmodels ARIMA a full walk over 200 bars took ~45 s per ticker.
    last = len(prices) - horizon
    step = max(1, (last - window) // _MAX_EVAL_POINTS)
    for i in range(last - 1, window - 1, -step):
        train = prices[:i]
        try:
            pred_ret = predictor_fn(train)
        except Exception:
            continue
        actual_ret = (prices[i + horizon] - prices[i]) / max(prices[i], 1e-9)
        pred_dir = _direction_from_return(pred_ret)
        actual_dir = _direction_from_return(actual_ret)
        if pred_dir == actual_dir:
            hits += 1
        total += 1
    return hits / total if total > 0 else 0.5


def _arima_forecast(prices: Sequence[float], horizon: int = FORECAST_HORIZON_DAYS) -> tuple[float, bool, str]:
    try:
        from statsmodels.tsa.arima.model import ARIMA  # type: ignore[import-untyped]

        returns = np.diff(np.log(np.maximum(prices, 1e-9)))
        if len(returns) < MIN_HISTORY_BARS:
            return 0.0, False, "insufficient_history"
        import warnings

        model = ARIMA(returns[-120:], order=(1, 0, 1))
        with warnings.catch_warnings():
            # Convergence/start-parameter notices: thousands of log lines per run, no action needed.
            warnings.simplefilter("ignore")
            fitted = model.fit()
        forecast = float(fitted.forecast(steps=1)[0])
        scaled = forecast * min(horizon, 10)
        return scaled, True, "statsmodels_arima"
    except ImportError:
        ret, ok = _ema_forecast(prices, horizon)
        return ret, ok, "ema_fallback_no_statsmodels"
    except Exception as exc:
        logger.debug("ARIMA forecast failed", error=str(exc))
        ret, ok = _ema_forecast(prices, horizon)
        return ret, ok, f"ema_fallback: {exc}"


def _ema_forecast(prices: Sequence[float], horizon: int) -> tuple[float, bool]:
    if len(prices) < 10:
        return 0.0, False
    short = np.mean(prices[-5:])
    long = np.mean(prices[-20:]) if len(prices) >= 20 else np.mean(prices)
    momentum = (short - long) / max(long, 1e-9)
    return momentum * min(horizon / 10.0, 1.0), True


def _momentum_forecast(prices: Sequence[float], horizon: int) -> tuple[float, bool]:
    if len(prices) < 15:
        return 0.0, False
    ret_5d = (prices[-1] - prices[-6]) / max(prices[-6], 1e-9) if len(prices) >= 6 else 0.0
    ret_20d = (prices[-1] - prices[-21]) / max(prices[-21], 1e-9) if len(prices) >= 21 else ret_5d
    blended = 0.6 * ret_5d + 0.4 * ret_20d
    return blended * (horizon / 10.0), True


def _should_invert_aapl_bearish_momentum(mom_acc: MomentumDirectionAccuracy) -> bool:
    """Invert anti-predictive AAPL bearish momentum when held-out accuracy is below floor."""
    if mom_acc.bearish_n < AAPL_BEARISH_INVERT_MIN_N:
        return False
    return mom_acc.bearish_accuracy < LIVE_ACCURACY_FLOOR


def _momentum_forecast_for_symbol(
    prices: Sequence[float],
    horizon: int,
    *,
    symbol: str | None = None,
    mom_dir_acc: MomentumDirectionAccuracy | None = None,
    invert_bearish: bool = False,
) -> tuple[float, bool]:
    ret, ok = _momentum_forecast(prices, horizon)
    if not ok or not invert_bearish:
        return ret, ok
    if _direction_from_return(ret) < 0:
        return -ret, ok
    return ret, ok


def bearish_inversion_improves_accuracy(
    prices: Sequence[float],
    *,
    window: int = 20,
    horizon: int = 5,
) -> tuple[bool, float, float]:
    """Return whether inverting bearish momentum beats raw on held-out walk-forward."""
    raw_hits = raw_total = inv_hits = inv_total = 0
    if len(prices) < window + horizon + 5:
        return False, 0.5, 0.5
    for i in range(window, len(prices) - horizon):
        train = prices[:i]
        pred_ret = _momentum_forecast(train, horizon)[0]
        pred_dir = _direction_from_return(pred_ret)
        if pred_dir >= 0:
            continue
        actual_ret = (prices[i + horizon] - prices[i]) / max(prices[i], 1e-9)
        actual_dir = _direction_from_return(actual_ret)
        if actual_dir == 0:
            continue
        raw_total += 1
        inv_total += 1
        raw_hits += int(pred_dir == actual_dir)
        inv_hits += int(-pred_dir == actual_dir)
    raw_acc = raw_hits / raw_total if raw_total else 0.5
    inv_acc = inv_hits / inv_total if inv_total else 0.5
    return inv_acc > raw_acc and inv_total >= AAPL_BEARISH_INVERT_MIN_N, raw_acc, inv_acc


def _momentum_bull_bear_accuracy(
    prices: Sequence[float],
    *,
    window: int = 20,
    horizon: int = 5,
) -> MomentumDirectionAccuracy:
    bull_hits = bull_total = bear_hits = bear_total = 0
    if len(prices) < window + horizon + 5:
        return MomentumDirectionAccuracy(0.5, 0.5, 0, 0)
    for i in range(window, len(prices) - horizon):
        train = prices[:i]
        try:
            pred_ret = _momentum_forecast(train, horizon)[0]
        except Exception:
            continue
        pred_dir = _direction_from_return(pred_ret)
        if pred_dir == 0:
            continue
        actual_ret = (prices[i + horizon] - prices[i]) / max(prices[i], 1e-9)
        actual_dir = _direction_from_return(actual_ret)
        hit = pred_dir == actual_dir
        if pred_dir > 0:
            bull_total += 1
            bull_hits += int(hit)
        else:
            bear_total += 1
            bear_hits += int(hit)
    bull_acc = bull_hits / bull_total if bull_total else 0.5
    bear_acc = bear_hits / bear_total if bear_total else 0.5
    return MomentumDirectionAccuracy(
        bullish_accuracy=bull_acc,
        bearish_accuracy=bear_acc,
        bullish_n=bull_total,
        bearish_n=bear_total,
    )


def _aapl_bearish_momentum_weight_factor(mom_acc: MomentumDirectionAccuracy) -> float:
    if mom_acc.bearish_n < 8:
        return 1.0
    if mom_acc.bearish_accuracy >= LIVE_ACCURACY_FLOOR:
        return 1.0
    scaled = max(AAPL_BEARISH_MOMENTUM_WEIGHT_CAP, mom_acc.bearish_accuracy / LIVE_ACCURACY_FLOOR)
    return min(1.0, scaled)


class EnsembleForecastEngine:
    """Combine ARIMA, momentum, LightGBM, N-BEATS, regime model with adaptive weighting."""

    def compute(
        self,
        prices: Sequence[float],
        *,
        symbol: str | None = None,
        momentum_score: float | None = None,
        calibrated_confidence: float = 0.5,
        horizon_days: int = FORECAST_HORIZON_DAYS,
        live_direction_accuracy: float | None = None,
        live_accuracy_sample_size: int = 0,
        sector_relative_strength: float = 0.0,
        order_book_imbalance: float = 0.0,
        news_sentiment: float = 0.0,
        lob_spread_bps: float = 0.0,
    ) -> EnsembleForecast:
        history_bars = len(prices)
        if history_bars < MIN_HISTORY_BARS:
            return EnsembleForecast(
                median_return=0.0,
                direction_consensus=0,
                models_agreeing=0,
                models_total=7,
                component_models=(),
                insufficient_history=True,
                history_bars=history_bars,
                default_view="sector_relative",
            )

        regime_label = RegimeEngine().classify_instrument(list(prices)).dominant_regime
        lgbm = get_gradient_boost_component()
        nbeats = get_nbeats_component()
        chronos = get_chronos_component()
        regime_models = get_regime_forecast_models()

        arima_ret, arima_ok, arima_note = _arima_forecast(prices, horizon_days)
        mom_dir_acc = (
            _momentum_bull_bear_accuracy(list(prices), horizon=horizon_days)
            if len(prices) >= MIN_HISTORY_BARS
            else MomentumDirectionAccuracy(0.5, 0.5, 0, 0)
        )
        invert_aapl_bearish = (
            symbol is not None
            and symbol.upper() == "AAPL"
            and _should_invert_aapl_bearish_momentum(mom_dir_acc)
        )
        mom_ret, mom_ok = _momentum_forecast_for_symbol(
            prices,
            horizon_days,
            symbol=symbol,
            mom_dir_acc=mom_dir_acc,
            invert_bearish=invert_aapl_bearish,
        )
        lgbm_pred = lgbm.predict(
            prices,
            symbol=symbol,
            horizon=horizon_days,
            regime_label=regime_label,
            sector_relative_strength=sector_relative_strength,
            order_book_imbalance=order_book_imbalance,
            news_sentiment=news_sentiment,
        )
        nbeats_pred = nbeats.predict(prices, horizon=horizon_days)
        chronos_pred = chronos.predict(prices, horizon=horizon_days)
        regime_pred = regime_models.predict(prices, horizon=horizon_days, regime_label=regime_label)
        lob = get_lob_component()
        lob_pred = lob.predict_from_imbalance(
            order_book_imbalance,
            spread_bps=lob_spread_bps,
            horizon=horizon_days,
        )

        arima_acc = _rolling_directional_accuracy(
            list(prices), lambda p: _arima_forecast(p, 5)[0]
        ) if arima_ok else 0.5
        mom_roll_acc = _rolling_directional_accuracy(
            list(prices),
            lambda p: _momentum_forecast_for_symbol(
                p,
                5,
                symbol=symbol,
                invert_bearish=invert_aapl_bearish,
            )[0],
        ) if mom_ok else 0.5
        lgbm_acc = (
            lgbm.rolling_accuracy(list(prices), horizon=5, symbol=symbol)
            if lgbm_pred.available
            else 0.5
        )
        nbeats_acc = nbeats.rolling_accuracy(list(prices), horizon=5) if nbeats_pred.available else 0.5
        chronos_acc = chronos.rolling_accuracy(list(prices), horizon=5) if chronos_pred.available else 0.5
        regime_acc = 0.52 if regime_pred.available else 0.5
        lob_acc = lob.rolling_accuracy(list(prices), horizon=horizon_days) if lob_pred.available else 0.5

        if not mom_ok:
            mom_dir_acc = MomentumDirectionAccuracy(0.5, 0.5, 0, 0)

        raw_models = [
            (ModelFamily.ARIMA, arima_ret, arima_ok, arima_acc, arima_note),
            (
                ModelFamily.MOMENTUM,
                mom_ret,
                mom_ok,
                mom_roll_acc,
                "aapl_bearish_inverted" if invert_aapl_bearish and _direction_from_return(mom_ret) != 0 else "",
            ),
            (ModelFamily.LIGHTGBM, lgbm_pred.expected_return, lgbm_pred.available, lgbm_acc, lgbm_pred.note),
            (ModelFamily.NBEATS, nbeats_pred.expected_return, nbeats_pred.available, nbeats_acc, nbeats_pred.note),
            (ModelFamily.CHRONOS, chronos_pred.expected_return, chronos_pred.available, chronos_acc, chronos_pred.note),
            (ModelFamily.REGIME_MODEL, regime_pred.expected_return, regime_pred.available, regime_acc, regime_pred.note),
            (ModelFamily.LOB_MICROSTRUCTURE, lob_pred.expected_return, lob_pred.available, lob_acc, lob_pred.note),
        ]

        available = [(f, r, a, n) for f, r, ok, a, n in raw_models if ok]
        if not available:
            return EnsembleForecast(
                median_return=0.0,
                direction_consensus=0,
                models_agreeing=0,
                models_total=7,
                component_models=(),
                insufficient_history=True,
                history_bars=history_bars,
                momentum_direction_accuracy=mom_dir_acc if mom_ok else None,
                default_view="sector_relative",
            )

        total_acc = sum(a for _, _, a, _ in available)
        components: list[ModelForecast] = []
        aapl_bear_factor = 1.0
        if (
            symbol
            and symbol.upper() == "AAPL"
            and mom_ok
            and not invert_aapl_bearish
        ):
            aapl_bear_factor = _aapl_bearish_momentum_weight_factor(mom_dir_acc)

        for family, ret, acc, note in available:
            w = acc / total_acc if total_acc > 0 else 1.0 / len(available)
            if (
                family == ModelFamily.MOMENTUM
                and _direction_from_return(ret) < 0
                and not invert_aapl_bearish
            ):
                w *= aapl_bear_factor
            components.append(
                ModelForecast(
                    family=family,
                    direction=_direction_from_return(ret),
                    expected_return=ret,
                    weight=w,
                    recent_accuracy=acc,
                    available=True,
                    note=note,
                )
            )

        total_w = sum(c.weight for c in components)
        if total_w > 0:
            components = tuple(
                ModelForecast(
                    family=c.family,
                    direction=c.direction,
                    expected_return=c.expected_return,
                    weight=c.weight / total_w,
                    recent_accuracy=c.recent_accuracy,
                    available=c.available,
                    note=c.note,
                )
                for c in components
            )
        else:
            components = tuple(components)

        weighted_sum = sum(c.weight * c.expected_return for c in components)
        weight_sum = sum(c.weight for c in components)
        median_return = weighted_sum / weight_sum if weight_sum > 0 else 0.0

        # Stacking meta-model replaces simple weighted average when trained.
        stack = get_stacking_meta_model().predict([c.expected_return for c in components])
        if stack.available and stack.note.startswith("stacking_meta"):
            median_return = stack.expected_return

        consensus_dir = _direction_from_return(median_return)

        direction_suppressed = False
        suppression_message: str | None = None
        single_name_low_confidence = True

        if (
            live_direction_accuracy is not None
            and live_accuracy_sample_size >= 5
            and live_direction_accuracy < LIVE_ACCURACY_FLOOR
            and consensus_dir != 0
        ):
            direction_suppressed = True
            suppression_message = "недостаточно предсказательной силы для направления"
            consensus_dir = 0
            median_return = 0.0
        elif consensus_dir != 0:
            single_name_low_confidence = True
            suppression_message = SINGLE_NAME_LOW_CONFIDENCE_MESSAGE_RU

        agreeing = sum(1 for c in components if c.direction == consensus_dir and consensus_dir != 0)
        if consensus_dir == 0:
            agreeing = sum(1 for c in components if c.direction == 0)

        overlays: dict[str, object] | None = None
        try:
            from app.services.trading_engines.runtime.overlays import forecast_engine_overlays

            overlays = forecast_engine_overlays(list(prices), symbol=symbol)
        except Exception:
            overlays = None

        try:
            from app.services.alpha.regime_gate import detect_regime
            from app.services.alpha.rules import donchian_breakout, simulate_turtle
            from app.services.alpha.veto import GateInputs, combine, decision_to_dict

            don = donchian_breakout(prices)
            turtle = simulate_turtle(prices)
            rets = np.diff(np.log(np.maximum(np.asarray(prices, dtype=float), 1e-9)))
            breadth = float(np.tanh(rets[-1] / (float(np.std(rets[-21:])) + 1e-8))) if rets.size >= 21 else 0.0
            gate = detect_regime(
                breadth=breadth,
                breadth_history=np.tanh(rets / (float(np.std(rets)) + 1e-8)).tolist() if rets.size >= 12 else None,
            )
            size = float(gate.size_mult)
            if turtle.units:
                size *= max(0.25, turtle.size_mult)
            dec = combine(
                GateInputs(
                    regime_alpha_on=gate.alpha_on,
                    regime_size_mult=size,
                    macro_veto=gate.macro_veto,
                    donchian_dir=don.direction,
                    turtle_dir=turtle.direction,
                    meta_take=True,
                    ml_dir=consensus_dir,
                )
            )
            gate_payload = {
                **decision_to_dict(dec),
                "regime": gate.label,
                "hmm_state": gate.hmm_state,
                "hmm_posterior": list(gate.posterior),
                "donchian": don.direction,
                "turtle": turtle.direction,
                "turtle_units": turtle.units,
                "turtle_system": turtle.system,
            }
            overlays = dict(overlays or {})
            overlays["alpha_gate"] = gate_payload
            if dec.vetoed_by:
                consensus_dir = 0
                median_return = 0.0
                direction_suppressed = True
                suppression_message = f"alpha_veto:{dec.vetoed_by}"
            else:
                median_return = abs(float(median_return)) * int(dec.direction) * float(dec.size_mult)
                consensus_dir = int(dec.direction)
                if dec.source == "rules" and dec.direction != 0:
                    agreeing = sum(1 for c in components if c.direction == consensus_dir)
        except Exception:
            consensus_dir = 0
            median_return = 0.0
            direction_suppressed = True
            suppression_message = "нет данных"
            agreeing = 0

        return EnsembleForecast(
            median_return=median_return,
            direction_consensus=consensus_dir,
            models_agreeing=agreeing,
            models_total=len(components),
            component_models=tuple(components),
            insufficient_history=False,
            history_bars=history_bars,
            direction_suppressed=direction_suppressed,
            suppression_message_ru=suppression_message,
            momentum_direction_accuracy=mom_dir_acc if mom_ok else None,
            single_name_low_confidence=single_name_low_confidence,
            default_view="sector_relative",
            engine_overlays=overlays,
        )


_engine = EnsembleForecastEngine()


def get_ensemble_forecast_engine() -> EnsembleForecastEngine:
    return _engine
