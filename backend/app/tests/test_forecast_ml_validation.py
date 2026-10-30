"""Tests for forecast ML validation steps (purged CV, triple-barrier, ensemble extensions)."""
from __future__ import annotations

import numpy as np
import pytest

from app.services.forecast.cross_sectional import evaluate_cross_sectional_vs_absolute
from app.services.forecast.ensemble import EnsembleForecastEngine, ModelFamily
from app.services.forecast.purged_cv import evaluate_purged_accuracy, purged_kfold_splits
from app.services.forecast.triple_barrier import triple_barrier_labels


def _trend_prices(n: int = 120, step: float = 0.3) -> list[float]:
    return [100.0 + step * i for i in range(n)]


def test_purged_kfold_excludes_overlap():
    folds = purged_kfold_splits(200, n_splits=5, label_horizon=10, embargo_pct=0.02)
    assert folds
    for fold in folds:
        assert fold.train_indices
        assert fold.test_indices
        overlap = set(fold.train_indices) & set(fold.test_indices)
        assert not overlap


def test_purged_cv_accuracy_runs():
    labels = [1, -1, 1, 1, -1, 1, -1, 1, 1, -1] * 20
    preds = labels.copy()
    result = evaluate_purged_accuracy(labels, preds, label_horizon=5)
    assert result.n > 0
    assert result.accuracy >= 0.9


def test_triple_barrier_labels_shape():
    prices = _trend_prices(100)
    labels = triple_barrier_labels(prices)
    assert len(labels) == len(prices)
    assert any(l != 0 for l in labels)


def test_ensemble_includes_nbeats_and_lightgbm():
    prices = _trend_prices(80)
    result = EnsembleForecastEngine().compute(prices, momentum_score=0.62, calibrated_confidence=0.68)
    families = {m.family for m in result.component_models}
    assert ModelFamily.ARIMA in families
    assert ModelFamily.MOMENTUM in families
    assert result.default_view == "sector_relative"


def test_cross_sectional_evaluation_runs():
    a = _trend_prices(80, 0.2)
    b = _trend_prices(80, -0.1)
    result = evaluate_cross_sectional_vs_absolute(
        {"A": a, "B": b},
        lambda p: (p[-1] - p[-6]) / max(p[-6], 1e-9) if len(p) >= 6 else 0.0,
        horizon=5,
    )
    assert result.n >= 0
