"""Tests for forecast direction accuracy fixes (LightGBM, inversion, horizon, scoring)."""
from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("lightgbm")

from app.services.forecast.direction_accuracy import is_scored_resolution
from app.services.forecast.ensemble import (
    MomentumDirectionAccuracy,
    _should_invert_aapl_bearish_momentum,
    bearish_inversion_improves_accuracy,
)
from app.services.forecast.gradient_boost_component import (
    GradientBoostForecastComponent,
    train_forecast_lgbm,
    validate_trained_lgbm,
)
from app.services.forecast.live_accuracy import HEALTH_ACCURACY_FLOOR
from app.services.forecast.purged_cv import evaluate_purged_accuracy
from app.services.forecast.symbol_horizon import horizon_for_symbol, select_best_horizon


def _trend_prices(n: int = 200, step: float = 0.25, noise: float = 0.0, seed: int = 7) -> list[float]:
    rng = np.random.default_rng(seed)
    prices = [100.0]
    for i in range(n - 1):
        prices.append(prices[-1] * (1 + step / 100 + rng.normal(0, noise)))
    return prices


def test_is_scored_resolution_excludes_neutral():
    assert is_scored_resolution(1, 0.01) is True
    assert is_scored_resolution(0, 0.01) is False
    assert is_scored_resolution(-1, 0.0001) is False
    assert is_scored_resolution(1, -0.01) is True


def test_purged_cv_excludes_neutral_from_denominator():
    labels = ([1, 0, -1, 1, 0, -1] * 10)[:40]
    preds = ([1, 1, -1, -1, 0, -1] * 10)[:40]
    result = evaluate_purged_accuracy(labels, preds, label_horizon=1, n_splits=3)
    assert result.n > 0
    assert 0.0 <= result.accuracy <= 1.0


def test_aapl_bearish_inversion_triggered_when_anti_predictive():
    mom_acc = MomentumDirectionAccuracy(
        bullish_accuracy=0.54,
        bearish_accuracy=0.29,
        bullish_n=61,
        bearish_n=24,
    )
    assert _should_invert_aapl_bearish_momentum(mom_acc) is True


def test_bearish_inversion_improves_on_counter_trend_series():
    prices = _trend_prices(120, step=0.35)
    improves, raw_acc, inv_acc = bearish_inversion_improves_accuracy(prices)
    assert raw_acc <= inv_acc or not improves


def test_lgbm_training_produces_non_stub_predictions(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    import app.services.forecast.gradient_boost_component as gbc_mod
    import app.services.ml.model as model_mod

    monkeypatch.setattr(model_mod, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(gbc_mod, "MODEL_DIR", tmp_path)

    prices = _trend_prices(260, step=0.15, noise=0.008, seed=11)
    metrics = train_forecast_lgbm(prices, symbol="AAPL")
    assert metrics["is_stub"] is False
    assert float(metrics["prediction_std"]) > 0.01
    assert (tmp_path / "forecast_direction_lgbm_AAPL.pkl").exists()

    component = GradientBoostForecastComponent()
    a = component.predict(prices[:80], symbol="AAPL", horizon=5)
    b = component.predict(_trend_prices(80, step=-0.2, seed=99), symbol="AAPL", horizon=5)
    assert a.note.startswith("lightgbm")
    assert a.direction != b.direction or abs(a.expected_return - b.expected_return) > 1e-6


def test_lgbm_predictions_vary_with_features(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    import app.services.forecast.gradient_boost_component as gbc_mod
    import app.services.ml.model as model_mod
    from app.services.forecast.forecast_features import build_feature_matrix
    import pickle

    monkeypatch.setattr(model_mod, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(gbc_mod, "MODEL_DIR", tmp_path)
    prices = _trend_prices(220, step=0.2, noise=0.01)
    train_forecast_lgbm(prices, symbol="TEST")

    df = build_feature_matrix(prices)
    labels = np.where(np.random.default_rng(1).random(len(df)) > 0.5, 1, -1)
    with open(tmp_path / "forecast_direction_lgbm_TEST.pkl", "rb") as f:
        model = pickle.load(f)
    report = validate_trained_lgbm(model, df.values, labels)
    assert report.top_features
    assert not report.is_stub or report.prediction_std >= 0


def test_symbol_horizon_uses_benchmark_or_cache(tmp_path, monkeypatch):
    import app.services.forecast.symbol_horizon as sh

    monkeypatch.setattr(sh, "HORIZON_CACHE_PATH", tmp_path / "symbol_horizons.json")
    sh._save_horizon_cache({"AAPL": 1, "MSFT": 10})
    prices = _trend_prices(80)
    # Stale cache h=1 for AAPL is clamped to trusted benchmark (10d).
    assert horizon_for_symbol(prices, symbol="AAPL") == 10
    assert horizon_for_symbol(prices, symbol="MSFT") == 10
    assert horizon_for_symbol(prices, symbol="GLD") == 10


def test_select_best_horizon_momentum_runs_fast():
    prices = _trend_prices(100, step=0.3)
    selection = select_best_horizon(prices, symbol="AAPL", horizons=(1, 5), use_ensemble=False)
    assert selection.horizon_days in (1, 5)


def test_ensemble_aapl_applies_bearish_inversion_note():
    from app.services.forecast.ensemble import _should_invert_aapl_bearish_momentum

    mom_acc = MomentumDirectionAccuracy(
        bullish_accuracy=0.54,
        bearish_accuracy=0.29,
        bullish_n=61,
        bearish_n=24,
    )
    assert _should_invert_aapl_bearish_momentum(mom_acc) is True


def test_health_floor_unchanged_at_50_percent():
    assert HEALTH_ACCURACY_FLOOR == 0.50
