"""Tests for per-component accuracy evaluation."""
from __future__ import annotations

import numpy as np

from app.services.forecast.component_evaluation import evaluate_component_accuracies


def test_component_evaluation_returns_wilson_rows():
    rng = np.random.default_rng(0)
    prices = [100.0]
    for _ in range(199):
        prices.append(prices[-1] * (1 + rng.normal(0.0002, 0.01)))
    rows = evaluate_component_accuracies(
        prices,
        symbol="AAPL",
        news_sentiment=0.15,
        order_book_imbalance=0.1,
    )
    assert rows
    names = {r.component for r in rows}
    assert "ensemble" in names
    assert "lob_microstructure" in names
    for row in rows:
        assert 0.0 <= row.ci_low <= row.ci_high <= 1.0
