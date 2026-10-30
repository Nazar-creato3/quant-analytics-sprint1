"""Watchlist-wide maneuver scan with mocked directional confidences."""
from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
from datetime import datetime, timezone

from app.services.ml.model import ModelPrediction
from app.services.risk.maneuver_generator import ManeuverGenerator


def _make_df(seed: int, trend: float = 0.001) -> pd.DataFrame:
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


def _mock_predictions(tickers: list[str], confidences: list[float]) -> MagicMock:
    clf = MagicMock()

    def _predict(df: pd.DataFrame, ticker: str) -> ModelPrediction:
        idx = tickers.index(ticker)
        conf = confidences[idx]
        direction = "long" if idx % 2 == 0 else "short"
        return ModelPrediction(
            ticker=ticker,
            direction=direction,
            confidence=conf,
            raw_score=conf,
            signal_strength=abs(conf - 0.5) * 2,
            features_used={"rsi_14": 50.0, "macd_bullish": 1.0, "volume_ratio": 1.1},
            model_version="mock",
            is_fallback=False,
        )

    clf.predict.side_effect = _predict
    # The generator computes features once and calls predict_from_features.
    clf.predict_from_features.side_effect = _predict
    return clf


class TestManeuverWatchlistScan:
    def test_seventeen_tickers_at_threshold_forty_yields_diverse_maneuvers(self, monkeypatch):
        tickers = [f"SYM{i:02d}" for i in range(17)]
        # Spread above and below 0.4 — expect primary + optional backfill.
        confidences = [
            0.72,
            0.65,
            0.58,
            0.52,
            0.48,
            0.46,
            0.44,
            0.42,
            0.55,
            0.61,
            0.39,
            0.37,
            0.68,
            0.51,
            0.47,
            0.43,
            0.41,
        ]
        market_data = {t: _make_df(i, trend=0.001 + i * 0.0001) for i, t in enumerate(tickers)}

        gen = ManeuverGenerator(portfolio_size=0.0, confidence_threshold=0.40)
        gen.classifier = _mock_predictions(tickers, confidences)

        outs = gen.generate(market_data=market_data)
        tradeable = [m for m in outs if not m.is_no_trade]

        assert len(tradeable) >= 5
        conf_values = sorted({round(m.confidence, 2) for m in tradeable})
        assert len(conf_values) >= 3

        filt = gen.last_confidence_filter
        assert filt is not None
        assert filt.above_threshold_count >= 5
        assert filt.tradeable_count == len(tradeable)

        notionals = [m.position_size_usd for m in tradeable if m.position_size_usd > 0]
        assert len(set(round(n, -1) for n in notionals)) >= 2

    def test_zero_portfolio_uses_sizing_fallback(self):
        tickers = ["A", "B", "C", "D", "E"]
        confidences = [0.62, 0.58, 0.55, 0.53, 0.51]
        market_data = {t: _make_df(i) for i, t in enumerate(tickers)}
        gen = ManeuverGenerator(portfolio_size=0.0, confidence_threshold=0.40)
        gen.classifier = _mock_predictions(tickers, confidences)
        outs = gen.generate(market_data=market_data)
        tradeable = [m for m in outs if not m.is_no_trade]
        assert len(tradeable) >= 3
        assert gen.portfolio_size > 0
