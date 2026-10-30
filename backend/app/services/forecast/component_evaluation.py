"""Per-component before/after accuracy with Wilson confidence intervals."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from app.services.forecast.chronos_component import get_chronos_component
from app.services.forecast.ensemble import (
    EnsembleForecastEngine,
    _arima_forecast,
    _momentum_forecast,
)
from app.services.forecast.gradient_boost_component import get_gradient_boost_component
from app.services.forecast.lob_component import get_lob_component
from app.services.forecast.nbeats_component import get_nbeats_component
from app.services.forecast.regime_models import get_regime_forecast_models
from app.services.regime.engine import RegimeEngine
from app.utils.wilson_ci import wilson_ci


@dataclass(frozen=True, slots=True)
class ComponentAccuracyRow:
    component: str
    accuracy: float
    n: int
    ci_low: float
    ci_high: float
    variant: str  # baseline | with_finbert | with_lob | combined

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "accuracy": self.accuracy,
            "n": self.n,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "variant": self.variant,
        }


def _sign(ret: float, threshold: float = 0.002) -> int:
    if ret > threshold:
        return 1
    if ret < -threshold:
        return -1
    return 0


def _walk_forward_accuracy(
    prices: Sequence[float],
    predictor: Callable[[Sequence[float]], tuple[float, bool]],
    *,
    horizon: int = 5,
    window: int = 20,
) -> tuple[int, int]:
    hits = total = 0
    if len(prices) < window + horizon + 5:
        return hits, total
    for i in range(window, len(prices) - horizon):
        pred_ret, ok = predictor(prices[: i + 1])
        if not ok:
            continue
        pred_dir = _sign(pred_ret)
        if pred_dir == 0:
            continue
        actual = (prices[i + horizon] - prices[i]) / max(prices[i], 1e-9)
        if _sign(actual) == pred_dir:
            hits += 1
        total += 1
    return hits, total


def _row(name: str, hits: int, total: int, variant: str) -> ComponentAccuracyRow:
    acc = hits / total if total else 0.0
    ci = wilson_ci(hits, total) if total else None
    return ComponentAccuracyRow(
        component=name,
        accuracy=round(acc, 4),
        n=total,
        ci_low=round(ci.ci_low, 4) if ci else 0.0,
        ci_high=round(ci.ci_high, 4) if ci else 1.0,
        variant=variant,
    )


def evaluate_component_accuracies(
    prices: Sequence[float],
    *,
    symbol: str | None = None,
    news_sentiment: float = 0.0,
    order_book_imbalance: float = 0.0,
    horizon: int = 5,
) -> list[ComponentAccuracyRow]:
    """Before/after style report for each ensemble member individually."""
    sym = (symbol or "BENCHMARK").upper()
    regime_engine = RegimeEngine()
    lgbm = get_gradient_boost_component()
    nbeats = get_nbeats_component()
    chronos = get_chronos_component()
    regime_models = get_regime_forecast_models()
    lob = get_lob_component()

    rows: list[ComponentAccuracyRow] = []

    h_arima, t_arima = _walk_forward_accuracy(
        prices, lambda p: _arima_forecast(p, horizon)[0:2], horizon=horizon
    )
    rows.append(_row("arima", h_arima, t_arima, "baseline"))

    h_mom, t_mom = _walk_forward_accuracy(
        prices, lambda p: _momentum_forecast(p, horizon), horizon=horizon
    )
    rows.append(_row("momentum", h_mom, t_mom, "baseline"))

    def _lgbm_base(p):
        r = lgbm.predict(p, symbol=sym, horizon=horizon)
        return r.expected_return, r.available

    h_lgbm0, t_lgbm0 = _walk_forward_accuracy(prices, _lgbm_base, horizon=horizon)
    rows.append(_row("lightgbm", h_lgbm0, t_lgbm0, "baseline"))

    def _lgbm_finbert(p):
        r = lgbm.predict(
            p,
            symbol=sym,
            horizon=horizon,
            news_sentiment=news_sentiment,
            order_book_imbalance=order_book_imbalance,
        )
        return r.expected_return, r.available

    h_lgbm1, t_lgbm1 = _walk_forward_accuracy(prices, _lgbm_finbert, horizon=horizon)
    rows.append(_row("lightgbm", h_lgbm1, t_lgbm1, "with_finbert"))

    h_nbeats, t_nbeats = _walk_forward_accuracy(
        prices,
        lambda p: (nbeats.predict(p, horizon=horizon).expected_return, nbeats.predict(p, horizon=horizon).available),
        horizon=horizon,
    )
    rows.append(_row("nbeats", h_nbeats, t_nbeats, "baseline"))

    h_chronos, t_chronos = _walk_forward_accuracy(
        prices,
        lambda p: (chronos.predict(p, horizon=horizon).expected_return, chronos.predict(p, horizon=horizon).available),
        horizon=horizon,
    )
    rows.append(_row("chronos", h_chronos, t_chronos, "baseline"))

    def _regime(p):
        label = regime_engine.classify_instrument(list(p)).dominant_regime
        r = regime_models.predict(p, horizon=horizon, regime_label=label)
        return r.expected_return, r.available

    h_reg, t_reg = _walk_forward_accuracy(prices, _regime, horizon=horizon)
    rows.append(_row("regime_model", h_reg, t_reg, "baseline"))

    def _lob_pred(p):
        r = lob.predict_from_imbalance(order_book_imbalance, horizon=horizon)
        return r.expected_return, r.available

    h_lob, t_lob = _walk_forward_accuracy(prices, _lob_pred, horizon=horizon)
    rows.append(_row("lob_microstructure", h_lob, t_lob, "with_lob"))

    ens = EnsembleForecastEngine()
    def _ensemble(p):
        r = ens.compute(
            p,
            symbol=sym,
            news_sentiment=news_sentiment,
            order_book_imbalance=order_book_imbalance,
            horizon_days=horizon,
        )
        return r.median_return, not r.insufficient_history

    h_ens, t_ens = _walk_forward_accuracy(prices, _ensemble, horizon=horizon)
    rows.append(_row("ensemble", h_ens, t_ens, "combined"))

    return rows
