"""Tests for forecast SHAP diagnostics."""
from __future__ import annotations

import numpy as np

from app.services.forecast.shap_diagnostics import run_forecast_shap_diagnostics


def _prices(n: int = 220) -> list[float]:
    rng = np.random.default_rng(42)
    out = [100.0]
    for _ in range(n - 1):
        out.append(out[-1] * (1 + rng.normal(0.0003, 0.012)))
    return out


def test_shap_diagnostics_runs_or_reports_gap():
    enrichments = [{"news_sentiment": 0.1, "order_book_imbalance": 0.05} for _ in _prices()]
    report = run_forecast_shap_diagnostics(_prices(), symbol="TEST", enrichments=enrichments)
    d = report.to_dict()
    assert d["symbol"] == "TEST"
    assert "global_top_features" in d
    if report.shap_available:
        assert report.n_validation >= 10
        assert report.global_top_features
