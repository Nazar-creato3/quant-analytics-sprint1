"""Tests for LOB microstructure features and component."""
from __future__ import annotations

import numpy as np

from app.schemas.orders import OrderBookLevel, OrderBookSnapshot
from app.services.forecast.lob_component import get_lob_component
from app.services.forecast.lob_features import lob_features_from_snapshot


def test_lob_features_from_real_depth():
    book = OrderBookSnapshot(
        ticker="SBER",
        bids=[OrderBookLevel(price=250.0, size=1000), OrderBookLevel(price=249.9, size=500)],
        asks=[OrderBookLevel(price=250.1, size=800), OrderBookLevel(price=250.2, size=400)],
        mid_price=250.05,
        spread_bps=4.0,
        depth_available=True,
        source="test",
    )
    feats = lob_features_from_snapshot(book)
    assert feats.depth_available is True
    assert feats.order_flow_imbalance > 0
    assert feats.depth_weighted_mid > 0


def test_lob_component_no_fake_depth():
    book = OrderBookSnapshot(
        ticker="SPY",
        bids=[],
        asks=[],
        depth_available=False,
        depth_unavailable_reason="no L2",
    )
    pred = get_lob_component().predict(book)
    assert pred.available is False


def test_lob_rolling_accuracy_runs():
    prices = list(100 * np.cumprod(1 + np.random.default_rng(1).normal(0, 0.01, 120)))
    acc = get_lob_component().rolling_accuracy(prices, horizon=5)
    assert 0.0 <= acc <= 1.0
