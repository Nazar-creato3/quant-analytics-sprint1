"""Unit tests for TreeSHAP explainability (spec Section 6.3)."""
from __future__ import annotations

import math
import pickle
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from app.services.market_analysis.shap_explainer import (
    compute_shap_top_factors,
    features_from_prices_volumes,
    shap_data_gap,
)
from app.services.ml.features import compute_features, get_feature_columns
from app.services.ml.model import MODEL_DIR, train_direction_model


def _synthetic_ohlcv(n: int = 280) -> pd.DataFrame:
    rows = []
    price = 100.0
    for i in range(n):
        price *= math.exp(0.0003 + 0.012 * math.sin(i / 7))
        rows.append(
            {
                "open": price * 0.999,
                "high": price * 1.005,
                "low": price * 0.995,
                "close": price,
                "volume": 1_000_000 + i * 1000,
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture
def trained_model_paths(tmp_path, monkeypatch):
    """Train a tiny LightGBM on synthetic data for SHAP tests."""
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    import app.services.ml.model as model_module

    monkeypatch.setattr(model_module, "MODEL_DIR", tmp_path)
    df = _synthetic_ohlcv(320)
    featured = compute_features(df)
    metrics = train_direction_model(featured, already_featured=True)
    assert metrics["n_train"] > 50
    model_module._classifier = None
    return tmp_path


class TestShapExplainer:
    def test_shap_data_gap_message(self):
        assert "SHAP" in shap_data_gap()

    def test_features_from_prices_volumes(self):
        prices = [100.0 + i * 0.1 for i in range(280)]
        volumes = [500_000.0] * len(prices)
        features = features_from_prices_volumes(prices, volumes)
        assert features
        assert "rsi_14" in features

    def test_compute_shap_without_model_reports_gap(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "PIPELINE_SKIP_SHAP", False)
        features = {col: 0.0 for col in get_feature_columns()}
        with patch("app.services.ml.model.get_classifier") as mock_get:
            mock_cls = mock_get.return_value
            mock_cls._model = None
            factors, ok, gaps = compute_shap_top_factors(features)
        assert factors is None
        assert ok is False
        assert any("LightGBM" in g for g in gaps)

    def test_compute_shap_skipped_when_pipeline_flag_set(self):
        features = {col: 0.0 for col in get_feature_columns()}
        factors, ok, gaps = compute_shap_top_factors(features)
        assert factors is None
        assert ok is False
        assert any("disabled" in g for g in gaps)

    def test_compute_shap_with_trained_model(self, trained_model_paths, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "PIPELINE_SKIP_SHAP", False)
        from app.services.ml.model import get_classifier

        prices = [100.0 + i * 0.08 for i in range(280)]
        volumes = [800_000.0] * len(prices)
        features = features_from_prices_volumes(prices, volumes)
        factors, ok, gaps = compute_shap_top_factors(features, top_n=3)
        assert ok is True
        assert factors is not None
        assert len(factors) == 3
        assert all(abs(f.contribution) >= 0 for f in factors)
        assert get_classifier()._model is not None

    def test_model_artifact_exists_after_training(self, trained_model_paths):
        model_path = trained_model_paths / "direction_lgbm.pkl"
        calib_path = trained_model_paths / "direction_lgbm_calibrator.pkl"
        assert model_path.exists()
        assert calib_path.exists()
        with open(model_path, "rb") as f:
            model = pickle.load(f)
        assert hasattr(model, "predict_proba")
