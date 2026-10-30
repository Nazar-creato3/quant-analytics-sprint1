"""E46-09: one regime label; GET /forecast uses forecast_core.for_ui."""
from __future__ import annotations

import pandas as pd

from app.api.v1.endpoints.forecast import attach_forecast_core
from app.schemas.forecast import ForecastOut
from app.services.forecast_core.service import for_ui
from app.services.market_regime.service import classify_from_prices
from app.services.ml.features import compute_regime
from app.services.qa.feature_flags import reset_for_tests
from app.services.risk_engine.series import put_series, reset as reset_series


def setup_function() -> None:
    reset_for_tests()
    reset_series()


def teardown_function() -> None:
    reset_series()
    reset_for_tests()


def test_e46_09_same_prices_one_regime_label():
    price = 100.0
    prices = [price]
    for _ in range(80):
        price *= 1.004
        prices.append(price)
    df = pd.DataFrame({"close": prices})
    canon = classify_from_prices(prices, scope="instrument", ticker="AAA")
    assert compute_regime(df) == canon["label"]
    assert compute_regime(df) in {"trend_up", "trend_down", "range", "volatility", "crisis", "insufficient"}
    assert compute_regime(df) not in {"bull", "bear", "sideways", "volatile"}


def test_e46_09_forecast_out_uses_for_ui_probability():
    rets = [0.01, 0.02, -0.005, 0.012, 0.008]
    put_series("SBER", rets)
    core = for_ui("SBER")
    stub = ForecastOut(symbol="SBER", instrument_id=1, confidence=0.99, probability_map={"legacy": 0.99})
    attached = attach_forecast_core(stub, "SBER")
    assert attached.source_metrics["forecast_core"]["probability"] == core["probability"]
    assert attached.confidence == core["probability"]
    assert attached.probability_map["forecast_core"] == core["probability"]
    assert attached.confidence != 0.99
