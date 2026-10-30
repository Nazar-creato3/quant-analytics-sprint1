"""Analysis-universe, regime breadth, hierarchy hints, news ranking, stale bars."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pathlib import Path

from app.services.market_data.nightly_digest import digest_is_fresh
from app.services.pipeline.io import daily_bar_is_stale
from app.services.pipeline.market_regime import compute_market_regime, regime_to_macro_score
from app.services.pipeline.tradeable_universe import merge_analysis_tickers
from app.services.risk.hierarchy_hints import (
    apply_hint_to_confidence,
    apply_hint_to_direction,
    hint_from_cached_forecast,
)
from app.services.risk.maneuver_debate import structural_debate
from app.services.risk.maneuver_generator import ManeuverCandidate
from app.services.ml.model import ModelPrediction
from app.services.risk.engine import TradeRiskResult


def test_universe_uses_digest_and_anchors_not_only_pins():
    tickers = merge_analysis_tickers(
        pins=["ZZZZ"],
        digest={
            "screen_top": [{"symbol": "NVDA", "change_pct": 4.0}],
            "top_movers": [{"symbol": "XOM", "change_pct": -3.0}],
        },
        cap=20,
    )
    assert "SPY" in tickers
    assert "QQQ" in tickers
    assert "NVDA" in tickers
    assert "XOM" in tickers
    assert "ZZZZ" in tickers


def test_empty_cache_is_not_a_hit():
    hint = hint_from_cached_forecast("AAPL", {"point_forecast": {}, "action_forecast": {}})
    assert hint.cache_hit is False


def test_wait_is_not_avoid():
    hint = hint_from_cached_forecast(
        "MSFT",
        {
            "point_forecast": {"expected_return_sign": 1},
            "action_forecast": {"recommendation": "wait"},
            "calibrated_confidence": 0.6,
        },
    )
    assert hint.cache_hit is True
    assert hint.is_wait is True
    assert hint.is_avoid is False
    assert hint.avoid is False


def test_hierarchy_can_set_direction_when_ml_is_neutral():
    direction, conf = apply_hint_to_direction(
        direction="neutral",
        confidence=0.4,
        hint=hint_from_cached_forecast(
            "AAPL",
            {
                "point_forecast": {"expected_return_sign": -1},
                "action_forecast": {"recommendation": "short"},
                "calibrated_confidence": 0.7,
            },
        ),
    )
    assert direction == "short"
    assert conf > 0.4


def test_agreeing_hint_lifts_confidence_more_than_noise():
    hint = hint_from_cached_forecast(
        "AAPL",
        {
            "point_forecast": {"expected_return_sign": 1},
            "action_forecast": {"recommendation": "buy"},
            "calibrated_confidence": 0.8,
        },
    )
    lifted = apply_hint_to_confidence(direction="long", confidence=0.55, hint=hint)
    assert lifted > 0.55


def test_missing_news_does_not_score_as_average():
    cand = ManeuverCandidate(
        ticker="AAPL",
        prediction=ModelPrediction(
            ticker="AAPL",
            direction="long",
            confidence=0.7,
            raw_score=0.7,
            signal_strength=0.4,
            features_used={},
            model_version="t",
        ),
        risk=TradeRiskResult(
            ticker="AAPL",
            direction="long",
            is_tradeable=True,
            reason="ok",
            entry_price=100,
            risk_reward_ratio=2.0,
        ),
        news_sentiment=0.0,
        news_article_count=0,
        event_score=0.0,
        macro_score=0.0,
        regime="sideways",
    )
    assert cand.news_events_component is None
    with_news = ManeuverCandidate(
        ticker="AAPL",
        prediction=cand.prediction,
        risk=cand.risk,
        news_sentiment=0.0,
        news_article_count=4,
        event_score=0.0,
        macro_score=0.0,
        regime="sideways",
    )
    assert with_news.news_events_component == 0.5
    assert cand.composite_score != with_news.composite_score


def test_week_old_digest_is_stale():
    now = datetime.now(timezone.utc)
    assert digest_is_fresh({"as_of": now.isoformat()}) is True
    assert digest_is_fresh({"as_of": (now - timedelta(days=6)).isoformat()}) is False


def test_pipeline_does_not_clobber_loaded_digest():
    source = (Path(__file__).resolve().parents[1] / "tasks" / "pipeline.py").read_text(encoding="utf-8")
    assert "digest: dict | None = None" not in source
    assert "nightly_digest_as_of" in source
    assert "load_latest_digest()" in source


def test_friday_bar_is_fresh_on_sunday():
    sunday = datetime(2026, 9, 20, 15, 0, tzinfo=timezone.utc)  # Sunday
    friday = datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc)
    assert daily_bar_is_stale(friday, now=sunday) is False
    old = friday - timedelta(days=10)
    assert daily_bar_is_stale(old, now=sunday) is True


def test_regime_uses_breadth_not_only_spy():
    import numpy as np
    import pandas as pd

    def _df(trend: float) -> pd.DataFrame:
        n = 80
        close = 100 * np.cumprod(np.ones(n) * (1 + trend))
        return pd.DataFrame(
            {"open": close, "high": close, "low": close, "close": close, "volume": np.ones(n) * 1e6}
        )

    data = {
        "SPY": _df(0.002),
        "QQQ": _df(0.002),
        "IWM": _df(-0.003),
        "AAPL": _df(0.004),
        "MSFT": _df(0.003),
    }
    out = compute_market_regime(data)
    assert out["regime"] in {"trend_up", "trend_down", "range", "volatility", "crisis", "insufficient"}
    assert "advances" in out
    assert abs(regime_to_macro_score("trend_up", breadth=0.5, digest_macro=0.2)) <= 1


def test_structural_debate_rejects_avoid_not_wait():
    def _c(ticker: str, rec: str) -> ManeuverCandidate:
        hint = hint_from_cached_forecast(
            ticker,
            {
                "point_forecast": {"expected_return_sign": 1},
                "action_forecast": {"recommendation": rec},
                "calibrated_confidence": 0.5,
            },
        )
        pred = ModelPrediction(
            ticker=ticker,
            direction="long",
            confidence=0.6,
            raw_score=0.6,
            signal_strength=0.3,
            features_used={},
            model_version="t",
        )
        return ManeuverCandidate(
            ticker=ticker,
            prediction=pred,
            risk=TradeRiskResult(ticker=ticker, direction="long", is_tradeable=True, reason="ok"),
            hierarchy_hint=hint,
        )

    result = structural_debate([_c("AAA", "avoid"), _c("BBB", "wait")])
    by_t = {d["ticker"]: d for d in result["decisions"]}
    assert by_t["AAA"]["approved"] is False
    assert by_t["BBB"]["approved"] is True
