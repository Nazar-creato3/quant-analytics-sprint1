from __future__ import annotations

import json

from app.services.forecast.forecast_features import FORECAST_FEATURE_COLUMNS, build_forecast_feature_row
from app.services.forecast.tier_c_capabilities import should_call_vendor
from app.services.forecast.tier_c_collect import collect_tier_c_extras
from app.services.forecast.tier_c_schema import TIER_C_FEATURE_COLUMNS
from app.services.forecast.tier_c_store import load_tier_c_extras


def test_c_slots_exist_and_stay_zero_without_store():
    for col in TIER_C_FEATURE_COLUMNS:
        assert col in FORECAST_FEATURE_COLUMNS
    extras = collect_tier_c_extras("AAPL")
    assert extras["c_tier_present"] == 0.0
    assert all(extras[k] == 0.0 for k in TIER_C_FEATURE_COLUMNS)


def test_live_vendor_calls_stay_off_by_default():
    assert should_call_vendor("sharadar") is False
    assert should_call_vendor("ravenpack") is False


def test_local_store_fills_slots_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.forecast.tier_c_store.settings.TIER_C_STORE_DIR",
        str(tmp_path),
        raising=False,
    )
    (tmp_path / "MSFT.json").write_text(
        json.dumps({"features": {"c_value_yield": 0.12, "c_quality": 0.4}}),
        encoding="utf-8",
    )
    extras = load_tier_c_extras("MSFT")
    assert extras["c_tier_present"] == 1.0
    assert extras["c_value_yield"] == 0.12
    row = build_forecast_feature_row(
        [100.0 + i * 0.1 for i in range(40)],
        extras=extras,
        allow_snapshot_fundamentals=True,
    )
    assert row["c_quality"] == 0.4
    train = build_forecast_feature_row(
        [100.0 + i * 0.1 for i in range(40)],
        extras=extras,
        allow_snapshot_fundamentals=False,
    )
    assert train["c_tier_present"] == 0.0
