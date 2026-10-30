"""Phase-1 continuation: Alpha#41 + Roll on the existing generate / book_gate path."""
from __future__ import annotations

import math

import pandas as pd

from app.services.ml.model import ModelPrediction
from app.services.quant_desk.microstructure_features import (
    ALPHA003_STATUS,
    KYLE_STATUS,
    alpha041_vwap_deviation,
    blend_composite,
    compute_maneuver_microstructure,
    roll_effective_spread,
    roll_size_mult,
    session_vwap_approx,
)
from app.services.quant_desk.overlays import desk_overlay
from app.services.risk.engine import TradeRiskResult
from app.services.risk.ensemble_shadow import compare_row
from app.services.risk.maneuver_generator import ManeuverCandidate


def _pred() -> ModelPrediction:
    return ModelPrediction(
        ticker="AAPL",
        direction="long",
        confidence=0.7,
        raw_score=0.6,
        signal_strength=0.5,
        features_used={},
        model_version="test",
    )


def _risk() -> TradeRiskResult:
    return TradeRiskResult(
        ticker="AAPL",
        direction="long",
        is_tradeable=True,
        reason="ok",
        entry_price=100.0,
        risk_reward_ratio=3.0,
    )


def test_alpha041_skips_trailing_nan_session():
    df = pd.DataFrame(
        {
            "open": [100.0, float("nan")],
            "high": [110.0, float("nan")],
            "low": [90.0, float("nan")],
            "close": [105.0, float("nan")],
        }
    )
    got = compute_maneuver_microstructure(df)
    expect = alpha041_vwap_deviation({"open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0})
    assert abs(got["vwap_deviation"] - expect["vwap_deviation"]) < 1e-12


def test_alpha041_matches_kakushadze_formula():
    row = {"open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0}
    vwap = session_vwap_approx(open_=100.0, high=110.0, low=90.0, close=105.0)
    assert abs(vwap - (105.0 + (100.0 + 110.0 + 90.0) / 3.0) / 2.0) < 1e-12
    got = alpha041_vwap_deviation(row)
    assert got["vwap_source"] == "kakushadze_ohlc_approx"
    assert abs(got["vwap_deviation"] - (math.sqrt(110.0 * 90.0) - vwap)) < 1e-12


def test_alpha041_moves_composite_score():
    bare = ManeuverCandidate(ticker="AAPL", prediction=_pred(), risk=_risk())
    with_feat = ManeuverCandidate(
        ticker="AAPL",
        prediction=_pred(),
        risk=_risk(),
        microstructure_meta={"vwap_deviation": 0.4, "vwap_deviation_rel": 0.004},
    )
    assert with_feat.composite_score != bare.composite_score
    assert with_feat.composite_score == blend_composite(bare.composite_score, 0.004)


def test_roll_nan_when_gamma_non_negative():
    # Strictly increasing prices → Δp > 0, γ1 typically ≥ 0.
    prices = [100.0 + i for i in range(80)]
    assert roll_effective_spread(prices) is None
    meta = compute_maneuver_microstructure(
        pd.DataFrame(
            {
                "open": prices,
                "high": [p + 0.1 for p in prices],
                "low": [p - 0.1 for p in prices],
                "close": prices,
                "volume": [1_000] * len(prices),
            }
        )
    )
    assert meta["spread_zscore"] is None
    assert meta["kyle_lambda"]["status"] == KYLE_STATUS["status"]
    assert meta["alpha003"]["status"] == ALPHA003_STATUS["status"]


def test_roll_defined_on_bid_ask_bounce():
    # Classic Roll bounce: p = m + c*q, q = ±1 alternating.
    m, c = 50.0, 0.25
    q = [1 if i % 2 == 0 else -1 for i in range(90)]
    prices = [m + c * qi for qi in q]
    spr = roll_effective_spread(prices, window=20)
    assert spr is not None
    assert spr > 0
    meta = compute_maneuver_microstructure(
        pd.DataFrame(
            {
                "open": prices,
                "high": [p + 0.01 for p in prices],
                "low": [p - 0.01 for p in prices],
                "close": prices,
                "volume": [2_000] * len(prices),
            }
        )
    )
    assert meta["spread"] is not None
    assert meta["spread_zscore"] is not None


def test_spread_zscore_shades_desk_overlay_not_book_gate_veto():
    common = dict(
        equity_usd=100_000,
        price=100.0,
        atr=2.0,
        current_usd=8_000,
        direction="long",
        realized_ann_vol=0.2,
        atr_pct=0.02,
        bid=100.0,
        ask=100.04,
        bid_sz=20,
        ask_sz=20,
    )
    base = desk_overlay(**common)
    wide = desk_overlay(**common, spread_zscore=2.4)
    assert base.allow is True and wide.allow is True
    assert wide.size_mult < base.size_mult
    assert "roll_spread_z" in wide.reasons
    assert roll_size_mult(None) == 1.0


def test_shadow_compare_row_carries_new_features():
    row = compare_row(
        ticker="MSFT",
        clf_direction="long",
        clf_confidence=0.6,
        forecast=None,
        features={
            "vwap_deviation": 0.12,
            "vwap_deviation_rel": 0.0003,
            "spread_zscore": 0.4,
            "kyle_lambda": dict(KYLE_STATUS),
            "alpha003": dict(ALPHA003_STATUS),
        },
    )
    assert row["features"]["vwap_deviation"] == 0.12
    assert row["features"]["spread_zscore"] == 0.4
    assert row["features"]["kyle_lambda"]["status"] == "blocked"
    assert row["used_for_maneuver"] is False
