"""Tests for new forecast ML stack pieces (MLflow export, Feast PIT, Chronos, ACI, BOCPD)."""
from __future__ import annotations

import numpy as np

from app.services.forecast.adaptive_conformal import adaptive_conformal_interval, record_conformal_coverage_from_resolution, update_aci_coverage
from app.services.forecast.bocpd import bocpd_changepoint_probability, combine_bocpd_with_hmm
from app.services.forecast.chronos_component import get_chronos_component
from app.services.forecast.feature_store import ForecastFeatureStore
from app.services.forecast.mlflow_registry import register_ensemble_run
from app.services.forecast.stacking import StackingMetaModel


def test_mlflow_local_export(tmp_path, monkeypatch):
    monkeypatch.setenv("MLFLOW_EXPORT_DIR", str(tmp_path))
    monkeypatch.setenv("MLFLOW_SYNC_DOCS", "false")
    out = register_ensemble_run(
        model_name="ensemble_baseline_v1",
        accuracy=0.43,
        n=561,
        promote_live=True,
        params={"test": "1"},
    )
    assert out["n"] == 561
    assert out["ci_low"] <= out["accuracy"] <= out["ci_high"]
    assert (tmp_path / "latest_registry.json").exists()


def test_feature_store_pit(tmp_path):
    store = ForecastFeatureStore(store_dir=tmp_path)
    prices = list(100 * np.cumprod(1 + np.random.normal(0, 0.01, 80)))
    n = store.materialize_from_prices("AAPL", prices)
    assert n > 0
    latest = store.latest_features("AAPL")
    assert latest is not None
    assert "returns_5d" in latest.features


def test_chronos_fallback_runs():
    prices = list(100 * np.cumprod(1 + np.random.normal(0, 0.01, 80)))
    pred = get_chronos_component().predict(prices, horizon=10)
    assert pred.available is True
    assert pred.note in {"chronos_t5_tiny", "chronos_unavailable_momentum"}


def test_stacking_uniform_average():
    meta = StackingMetaModel()
    meta._model = None
    r = meta.predict([0.01, -0.02, 0.03])
    assert r.available
    assert r.note == "uniform_average"


def test_stacking_train_produces_meta(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    import app.services.forecast.stacking as stacking_mod
    import app.services.ml.model as model_mod

    monkeypatch.setattr(stacking_mod, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(model_mod, "MODEL_DIR", tmp_path)
    stacking_mod._META = None
    prices = list(100 * np.cumprod(1 + np.random.normal(0, 0.01, 200)))
    out = stacking_mod.train_stacking_meta_from_prices(prices, method="logistic")
    assert out["ok"] is True
    assert (tmp_path / "forecast_stacking_meta.pkl").exists()
    meta = stacking_mod.reset_stacking_meta_model()
    r = meta.predict([0.01, -0.02, 0.015, 0.0, 0.005, -0.01])
    assert r.note.startswith("stacking_meta")


def test_bocpd_and_aci():
    prices = list(100 * np.cumprod(1 + np.random.normal(0, 0.01, 120)))
    # Inject a regime shift
    prices = prices[:60] + list(np.array(prices[60:]) * 0.7)
    bocpd = bocpd_changepoint_probability(prices)
    assert 0.0 <= bocpd.changepoint_probability <= 1.0
    combined = combine_bocpd_with_hmm(prices, "bullish_trend", hmm_confidence=0.8)
    assert combined.hmm_regime == "bullish_trend"
    interval = adaptive_conformal_interval(prices, 0.01, symbol="TEST")
    assert interval.upper_90 >= interval.lower_90
    assert "conformal" in interval.method or "aci" in interval.method
    st = update_aci_coverage("TEST:90", False, alpha=0.10)
    assert st.alpha_t >= 0.10
    upd = record_conformal_coverage_from_resolution(
        "TEST",
        0.02,
        {
            "lower_70": -0.05,
            "upper_70": 0.05,
            "lower_90": -0.08,
            "upper_90": 0.08,
        },
    )
    assert upd.get("updated") is True
