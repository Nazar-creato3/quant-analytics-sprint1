"""Tests for user confidence-threshold filtering and empty-state suggestions."""
from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime, timezone

from app.services.risk.confidence_filter import (
    build_confidence_empty_message,
    build_confidence_filter_result,
    suggest_confidence_threshold,
)
from app.services.risk.maneuver_generator import ManeuverGenerator


def _make_df(seed: int = 0, trend: float = 0.002) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = 300
    dates = pd.date_range(end=datetime.now(timezone.utc), periods=n, freq="D")
    close = 100 * np.cumprod(1 + rng.normal(0, 0.02, n) + trend)
    return pd.DataFrame(
        {
            "open": close * 0.99,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": rng.integers(1_000_000, 5_000_000, n),
        },
        index=dates,
    )


class TestConfidenceFilterHelpers:
    def test_suggest_threshold_floors_to_five_percent_and_caps_at_seventy(self):
        assert suggest_confidence_threshold(0.73) == 0.70
        assert suggest_confidence_threshold(0.58) == 0.55
        assert suggest_confidence_threshold(0.48) == 0.45

    def test_empty_message_matches_required_meaning(self):
        msg = build_confidence_empty_message(0.65)
        assert "Сделок, подходящих под такой порог уверенности, нет" in msg
        assert "Порог нереалистично высокий" in msg
        assert "65%" in msg
        assert "чтобы увидеть возможные сделки" in msg

    def test_build_result_marks_unrealistic_threshold(self):
        result = build_confidence_filter_result(
            0.96,
            max_available_confidence=0.62,
            tradeable_count=0,
        )
        assert result.threshold_too_high is True
        assert result.suggested_threshold == 0.60
        assert result.message is not None
        assert "60%" in result.message

    def test_build_result_normal_when_threshold_is_reachable(self):
        result = build_confidence_filter_result(
            0.55,
            max_available_confidence=0.62,
            tradeable_count=0,
        )
        assert result.threshold_too_high is False
        assert result.message is None

    def test_moderate_threshold_empty_suggests_reachable_level(self):
        result = build_confidence_filter_result(
            0.70,
            max_available_confidence=0.62,
            tradeable_count=0,
        )
        assert result.threshold_too_high is False
        assert result.suggested_threshold == 0.60
        assert result.message is not None
        assert "60%" in result.message

    def test_backfill_only_sets_honest_message(self):
        result = build_confidence_filter_result(
            0.65,
            max_available_confidence=0.58,
            tradeable_count=3,
            above_threshold_count=0,
            backfill_count=3,
        )
        assert result.message is not None
        assert "65%" in result.message
        assert "ниже порога" in result.message

    def test_extreme_threshold_triggers_suggestion(self):
        result = build_confidence_filter_result(
            0.96,
            max_available_confidence=0.62,
            tradeable_count=0,
        )
        assert result.threshold_too_high is True
        assert result.suggested_threshold is not None


class TestManeuverGeneratorConfidenceThreshold:
    def test_generator_wires_confidence_threshold_to_risk_engine(self):
        gen = ManeuverGenerator(portfolio_size=500.0, confidence_threshold=0.72)
        assert gen.confidence_threshold == 0.72
        assert gen.risk_engine.params.confidence_threshold == 0.72

    def test_high_threshold_returns_best_available_with_honest_flag(self):
        market_data = {f"T{i}": _make_df(i, trend=0.003 + i * 0.0002) for i in range(12)}
        gen = ManeuverGenerator(confidence_threshold=0.99, portfolio_size=10_000.0)
        outs = gen.generate(market_data=market_data)
        tradeable = [m for m in outs if not m.is_no_trade]
        assert len(tradeable) >= 1
        assert any(m.below_confidence_threshold for m in tradeable)
        assert gen.last_confidence_filter is not None
        assert gen.last_confidence_filter.tradeable_count >= 1

    def test_low_threshold_returns_at_least_one_maneuver(self):
        market_data = {f"T{i}": _make_df(i, trend=0.003 + i * 0.0002) for i in range(12)}
        gen = ManeuverGenerator(confidence_threshold=0.05, portfolio_size=10_000.0)
        outs = gen.generate(market_data=market_data)
        tradeable = [m for m in outs if not m.is_no_trade]
        assert len(tradeable) >= 1

    def test_empty_candidate_set_honestly_zero_tradeable(self, monkeypatch):
        gen = ManeuverGenerator(confidence_threshold=0.50, portfolio_size=10_000.0)
        monkeypatch.setattr(gen, "_analyze_ticker", lambda *a, **k: None)
        outs = gen.generate(market_data={"X": _make_df(1)})
        tradeable = [m for m in outs if not m.is_no_trade]
        assert tradeable == []
        assert gen.last_confidence_filter is not None
        assert gen.last_confidence_filter.tradeable_count == 0

    def test_filter_metadata_matches_tradeable_list(self):
        market_data = {f"T{i}": _make_df(i, trend=0.003 + i * 0.0002) for i in range(8)}
        gen = ManeuverGenerator(confidence_threshold=0.55, portfolio_size=10_000.0)
        outs = gen.generate(market_data=market_data)
        tradeable = [m for m in outs if not m.is_no_trade]
        filt = gen.last_confidence_filter
        assert filt is not None
        assert filt.tradeable_count == len(tradeable)

    def test_reasonable_threshold_still_produces_tradeable_maneuvers(self):
        market_data = {f"T{i}": _make_df(i, trend=0.003 + i * 0.0002) for i in range(12)}
        gen = ManeuverGenerator(portfolio_size=10_000.0, confidence_threshold=0.45)
        outs = gen.generate(market_data=market_data)
        tradeable = [m for m in outs if not m.is_no_trade]
        assert len(tradeable) >= 3

    def test_backfill_runs_second_pass_when_first_empty_at_threshold(self, monkeypatch):
        gen = ManeuverGenerator(portfolio_size=10_000.0, confidence_threshold=0.50)
        calls: list[list] = []

        original = gen._select_tradeable_maneuvers

        def _wrapped(candidates, state, **kwargs):
            calls.append(list(candidates))
            if len(calls) == 1:
                return []
            return original(candidates, state, **kwargs)

        monkeypatch.setattr(gen, "_select_tradeable_maneuvers", _wrapped)
        market_data = {f"T{i}": _make_df(i, trend=0.003 + i * 0.0002) for i in range(12)}
        outs = gen.generate(market_data=market_data)
        max_conf = gen.last_confidence_filter.max_available_confidence
        if max_conf is not None and max_conf >= 0.50:
            assert len(calls) >= 2
        tradeable = [m for m in outs if not m.is_no_trade]
        if max_conf is not None and max_conf >= 0.50:
            assert len(tradeable) >= 1

    def test_neutral_ml_cluster_at_threshold_forty_three_yields_tradeable(self, monkeypatch):
        """Calibrated models often sit at prob≈0.50 — must not zero the book at 0.43."""
        from unittest.mock import MagicMock

        from app.services.ml.model import ModelPrediction

        tickers = [f"SYM{i}" for i in range(10)]
        market_data = {t: _make_df(i, trend=0.001 + i * 0.0002) for i, t in enumerate(tickers)}
        clf = MagicMock()

        def _predict(df: pd.DataFrame, ticker: str) -> ModelPrediction:
            idx = tickers.index(ticker)
            rsi = 35.0 + (idx % 5) * 6.0
            return ModelPrediction(
                ticker=ticker,
                direction="neutral",
                confidence=0.50,
                raw_score=0.50,
                signal_strength=0.0,
                features_used={
                    "rsi_14": rsi,
                    "macd_bullish": 1.0 if idx % 2 == 0 else 0.0,
                    "volume_ratio": 1.1,
                    "roc_5": 1.5 if idx % 2 == 0 else -1.5,
                    "sma_cross_5_20": 1.0 if idx % 2 == 0 else 0.0,
                    "price_vs_sma20": 0.02 if idx % 2 == 0 else -0.02,
                    "bb_position": 0.5,
                },
                model_version="mock_neutral_cluster",
                is_fallback=False,
            )

        clf.predict.side_effect = _predict
        clf.predict_from_features.side_effect = _predict
        gen = ManeuverGenerator(portfolio_size=10_000.0, confidence_threshold=0.43)
        gen.classifier = clf
        outs = gen.generate(market_data=market_data)
        tradeable = [m for m in outs if not m.is_no_trade]
        assert len(tradeable) >= 3
        assert gen.last_confidence_filter is not None
        assert gen.last_confidence_filter.tradeable_count >= 3
        for m in tradeable:
            assert m.direction in ("long", "short")
            assert m.position_size_usd > 0
