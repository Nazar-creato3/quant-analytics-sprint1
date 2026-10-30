"""Excess labels, 1–10 mapping, honest features, adaptive trees."""
from __future__ import annotations

import numpy as np
import pytest

from app.services.forecast.excess_labels import benchmark_symbol_for, excess_direction_labels
from app.services.forecast.forecast_features import FORECAST_FEATURE_COLUMNS, build_forecast_feature_row
from app.services.forecast.fund_news_extras import fundamentals_to_extras
from app.services.forecast.market_beat import build_market_beat, probability_to_score_1_10
from app.services.forecast.tier_b_universe import daily_retrain_symbols


def test_probability_to_score_mapping():
    assert probability_to_score_1_10(0.50) == 5
    assert probability_to_score_1_10(0.75) == 8
    assert probability_to_score_1_10(0.20) == 2
    assert probability_to_score_1_10(0.0) == 1
    assert probability_to_score_1_10(1.0) == 10


def test_excess_labels_beat_benchmark():
    asset = [100.0 + i for i in range(40)]
    bench = [100.0] * 40
    labels = excess_direction_labels(asset, bench, horizon=20)
    assert labels[0] == 1
    assert labels[-1] == 0
    assert sum(1 for x in labels if x != 0) == 20


def test_excess_labels_without_benchmark_uses_own_return():
    falling = [100.0 - i for i in range(30)]
    labels = excess_direction_labels(falling, None, horizon=5)
    assert labels[0] == -1


def test_benchmark_symbol_routing():
    assert benchmark_symbol_for("AAPL") == "SPY"
    assert benchmark_symbol_for("BTC-USD") == "BTC-USD"
    assert benchmark_symbol_for("ETHUSDT") == "BTC-USD"


def test_feature_row_has_honest_windows_and_aliases():
    prices = list(np.cumprod(np.concatenate(([100.0], 1 + np.random.default_rng(2).normal(0, 0.01, 80)))))
    row = build_forecast_feature_row(prices, news_sentiment=0.2)
    assert len(FORECAST_FEATURE_COLUMNS) >= 120
    assert row["returns_5d"] == row["ret_5"]
    assert row["returns_20d"] == row["ret_21"]
    assert row["tech_present"] == 1.0
    assert row["news_present"] == 1.0
    assert row["fund_present"] == 0.0
    extras = fundamentals_to_extras({"pe_ratio": 20, "roe": 0.2, "profit_margin": 0.1})
    row2 = build_forecast_feature_row(prices, extras=extras)
    assert row2["fund_present"] == 1.0
    assert row2["fmp_pe_inv"] == pytest.approx(0.05)


def test_market_beat_hides_empty_fund_news():
    prices = list(np.linspace(100, 110, 40))
    features = build_forecast_feature_row(prices)
    payload = build_market_beat(
        symbol="AAPL",
        p_beat_20=0.72,
        p_beat_60=0.61,
        features=features,
        prices=prices,
        live_accuracy=0.55,
        live_n=12,
        model_accepted=True,
    )
    assert payload["score_20"] == 7
    assert payload["score_60"] == 6
    assert payload["subscores"]["technical"]["available"] is True
    assert payload["subscores"]["fundamental"] is None
    assert payload["subscores"]["news"] is None
    assert payload["subscores"]["tier_c"] is None
    assert "обогнать свой рынок" in payload["explanation_ru"]


def test_volume_and_excess_features_from_ohlcv():
    prices = list(np.linspace(100, 120, 80))
    vols = list(np.linspace(1e6, 2e6, 80))
    highs = [p * 1.01 for p in prices]
    lows = [p * 0.99 for p in prices]
    bench = list(np.linspace(100, 105, 80))
    row = build_forecast_feature_row(
        prices,
        volumes=vols,
        highs=highs,
        lows=lows,
        benchmark=bench,
        extras={"fmp_roe": 0.3, "fund_present": 1.0},
        allow_snapshot_fundamentals=False,
    )
    assert row["vol_ratio_20"] != 0.0
    assert row["hl_range_14"] > 0
    assert row["excess_ret_21"] != 0.0
    assert row["fund_present"] == 0.0
    assert row["fmp_roe"] == 0.0


def test_excess_track_hit_logic():
    from app.services.forecast.excess_track import attach_excess_track_fields, excess_hit, summarize_excess_payloads

    assert excess_hit(predicted=True, excess=0.02) is True
    assert excess_hit(predicted=True, excess=-0.01) is False
    payload = {"market_beat": {"symbol": "AAPL", "p_beat_20": 0.7, "p_beat_60": 0.4}}
    attach_excess_track_fields(
        payload, asset_20=0.05, bench_20=0.01, asset_60=0.02, bench_60=0.03
    )
    assert payload["excess_track"]["hit_20"] is True
    assert payload["excess_track"]["hit_60"] is True
    summary = summarize_excess_payloads([payload], horizon=20)
    assert summary["sample_size"] == 1
    assert summary["accuracy"] == 1.0


def test_panel_trains_when_universe_is_wide_enough(tmp_path, monkeypatch):
    pytest.importorskip("lightgbm")
    import app.services.forecast.gradient_boost_component as gbc
    import app.services.forecast.panel_train as panel
    import app.services.ml.model as model_mod

    monkeypatch.setattr(model_mod, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(gbc, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(panel, "MODEL_DIR", tmp_path)

    rng = np.random.default_rng(3)
    universe = {}
    for i, name in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]):
        rets = rng.normal(0.001 * (i - 2), 0.015, 160)
        closes = list(100 * np.cumprod(1 + rets))
        universe[name] = {
            "closes": closes,
            "highs": [c * 1.01 for c in closes],
            "lows": [c * 0.99 for c in closes],
            "volumes": list(rng.uniform(1e5, 2e5, 160)),
            "benchmark": list(100 * np.cumprod(1 + rng.normal(0.0004, 0.01, 160))),
        }
    metrics = panel.train_panel_lgbm(universe, horizon=20)
    assert metrics["n_train"] >= 200
    assert metrics["n_estimators"] >= 180
    assert (tmp_path / "forecast_direction_lgbm_PANEL.pkl").exists()


def test_tier_a_b_universe_includes_watchlist_and_liquid():
    uni = daily_retrain_symbols(["XYZ"])
    assert uni[0] == "XYZ"
    assert "SPY" in uni
    assert "BTC-USD" in uni
    assert "NVDA" in uni

