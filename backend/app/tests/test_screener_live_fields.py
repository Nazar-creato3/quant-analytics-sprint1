"""Screener live fields: xFinLink/Yahoo parsing, computed risk, merge rules."""
from __future__ import annotations

import math
import random

from app.services.screener.fundamentals import (
    merge_live,
    parse_xfinlink_metrics,
    parse_yahoo_info,
    risk_from_closes,
)


def test_xfinlink_market_cap_is_converted_from_millions():
    payload = {
        "data": [{"ticker": "AAPL", "pe_ratio": 39.1, "market_cap": 4977636.97}],
        "meta": {"units": "millions_usd"},
    }
    out = parse_xfinlink_metrics(payload)
    assert out["pe"] == 39.1
    assert math.isclose(out["market_cap"], 4_977_636_970_000, rel_tol=1e-9)
    assert parse_xfinlink_metrics({"data": []}) == {}


def test_yahoo_info_mapping_and_dividend_percent():
    out = parse_yahoo_info(
        {"marketCap": 3.1e12, "trailingPE": 33.2, "beta": 1.2, "trailingAnnualDividendYield": 0.0044, "averageVolume": 5e7}
    )
    assert out["market_cap"] == 3.1e12 and out["pe"] == 33.2 and out["beta"] == 1.2
    assert math.isclose(out["dividend"], 0.44)
    assert parse_yahoo_info({})["pe"] is None


def test_risk_from_closes_reasonable_and_beta_one_vs_itself():
    random.seed(1)
    px = [100.0]
    for _ in range(252):
        px.append(px[-1] * math.exp(random.gauss(0, 0.02)))
    risk = risk_from_closes(px, px)
    assert 0.2 < risk["volatility"] < 0.45  # ~2 % daily → ~32 % annual
    assert 0.02 < risk["es_975"] < 0.08
    assert math.isclose(risk["beta"], 1.0, rel_tol=1e-9)
    assert risk_from_closes(px[:10]) == {}


def test_merge_fills_only_missing_and_updates_status():
    row = {"symbol": "AAPL", "pe": None, "pe_status": "нет данных", "beta": 1.5, "beta_status": "ok", "market_cap": None}
    out = merge_live(row, {"pe": 30.0, "beta": 1.1, "market_cap": 3e12, "fundamentals_source": "yahoo"})
    assert out["pe"] == 30.0 and out["pe_status"] == "ok"
    assert out["beta"] == 1.5  # catalog value wins
    assert out["market_cap"] == 3e12
    assert merge_live(row, None) == row
