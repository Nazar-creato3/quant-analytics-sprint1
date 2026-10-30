"""
Feature engineering pipeline.
Computes technical indicators from OHLCV data.
Returns a feature DataFrame ready for ML inference.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.core.logging import get_logger

logger = get_logger(__name__)


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Given a OHLCV DataFrame with columns [open, high, low, close, volume],
    compute all technical features. Returns augmented DataFrame.

    Args:
        df: DataFrame with DatetimeIndex, columns [open, high, low, close, volume]

    Returns:
        DataFrame with additional feature columns. NaN rows are preserved for alignment.
    """
    if df.empty or len(df) < 20:
        logger.warning("Insufficient bars for feature computation", rows=len(df))
        return df

    df = df.copy()

    # ── Price transforms ───────────────────────────────────────────────────────
    df["returns_1d"] = df["close"].pct_change(1)
    df["returns_3d"] = df["close"].pct_change(3)
    df["returns_5d"] = df["close"].pct_change(5)
    df["returns_10d"] = df["close"].pct_change(10)
    df["returns_20d"] = df["close"].pct_change(20)

    df["log_return"] = np.log(df["close"] / df["close"].shift(1))

    # ── Moving averages ────────────────────────────────────────────────────────
    for window in [5, 10, 20, 50, 200]:
        df[f"sma_{window}"] = df["close"].rolling(window).mean()
        df[f"ema_{window}"] = df["close"].ewm(span=window, adjust=False).mean()

    df["sma_cross_5_20"] = (df["sma_5"] > df["sma_20"]).astype("int64")
    df["sma_cross_20_50"] = (df["sma_20"] > df["sma_50"]).astype("int64")
    df["price_vs_sma20"] = (df["close"] - df["sma_20"]) / df["sma_20"]
    df["price_vs_sma50"] = (df["close"] - df["sma_50"]) / df["sma_50"]

    # ── Volatility ────────────────────────────────────────────────────────────
    df["volatility_5d"] = df["log_return"].rolling(5).std() * np.sqrt(252)
    df["volatility_10d"] = df["log_return"].rolling(10).std() * np.sqrt(252)
    df["volatility_20d"] = df["log_return"].rolling(20).std() * np.sqrt(252)

    # ATR
    df["tr"] = np.maximum(
        df["high"] - df["low"],
        np.maximum(
            abs(df["high"] - df["close"].shift(1)),
            abs(df["low"] - df["close"].shift(1)),
        ),
    )
    df["atr_14"] = df["tr"].rolling(14).mean()
    df["atr_pct"] = df["atr_14"] / df["close"]

    # Bollinger Bands
    df["bb_mid"] = df["close"].rolling(20).mean()
    bb_std = df["close"].rolling(20).std()
    df["bb_upper"] = df["bb_mid"] + 2 * bb_std
    df["bb_lower"] = df["bb_mid"] - 2 * bb_std
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]
    df["bb_position"] = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"] + 1e-10)

    # ── Momentum ──────────────────────────────────────────────────────────────
    # RSI
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-10)
    df["rsi_14"] = 100 - (100 / (1 + rs))
    df["rsi_overbought"] = (df["rsi_14"] > 70).astype("int64")
    df["rsi_oversold"] = (df["rsi_14"] < 30).astype("int64")

    # MACD
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    df["macd_bullish"] = (df["macd"] > df["macd_signal"]).astype("int64")

    # Rate of Change
    df["roc_5"] = df["close"].pct_change(5) * 100
    df["roc_10"] = df["close"].pct_change(10) * 100
    df["roc_20"] = df["close"].pct_change(20) * 100

    # ── Volume ────────────────────────────────────────────────────────────────
    df["volume_sma_20"] = df["volume"].rolling(20).mean()
    df["volume_ratio"] = df["volume"] / (df["volume_sma_20"] + 1e-10)
    df["volume_trend"] = df["volume"].rolling(5).mean() / (df["volume"].rolling(20).mean() + 1e-10)

    # On-Balance Volume
    df["obv"] = (np.sign(df["close"].diff()) * df["volume"]).cumsum()
    df["obv_slope"] = df["obv"].diff(5)

    # ── Candlestick patterns (simple) ─────────────────────────────────────────
    body = df["close"] - df["open"]
    wick_up = df["high"] - df[["close", "open"]].max(axis=1)
    wick_down = df[["close", "open"]].min(axis=1) - df["low"]

    df["candle_body"] = body
    df["candle_wick_up"] = wick_up
    df["candle_wick_down"] = wick_down
    df["is_bullish"] = (body > 0).astype("int64")
    df["doji"] = (abs(body) < df["atr_14"] * 0.1).astype("int64")

    # ── Support / Resistance levels ────────────────────────────────────────────
    df["high_20d"] = df["high"].rolling(20).max()
    df["low_20d"] = df["low"].rolling(20).min()
    prev_high_20 = df["high"].shift(1).rolling(20).max()
    df["donchian_20_break"] = (df["close"] > prev_high_20).astype("int64")
    df["vol_of_vol_20"] = df["volatility_20d"].rolling(20).std()
    df["high_50d"] = df["high"].rolling(50).max()
    df["low_50d"] = df["low"].rolling(50).min()
    df["pct_from_52w_high"] = (df["close"] - df["high"].rolling(252).max()) / df["high"].rolling(252).max()

    # ── Target variable (for training) ────────────────────────────────────────
    df["target_1d"] = (df["close"].shift(-1) > df["close"]).astype("int64")
    df["target_5d"] = (df["close"].shift(-5) > df["close"]).astype("int64")
    df["target_return_5d"] = df["close"].shift(-5) / df["close"] - 1

    return df


def get_feature_columns() -> list[str]:
    """Return the canonical list of feature columns used by ML models."""
    return [
        "returns_1d", "returns_3d", "returns_5d", "returns_10d", "returns_20d",
        "log_return",
        "sma_cross_5_20", "sma_cross_20_50",
        "price_vs_sma20", "price_vs_sma50",
        "volatility_5d", "volatility_10d", "volatility_20d",
        "atr_pct", "bb_width", "bb_position",
        "rsi_14", "rsi_overbought", "rsi_oversold",
        "macd", "macd_hist", "macd_bullish",
        "roc_5", "roc_10", "roc_20",
        "volume_ratio", "volume_trend", "obv_slope",
        "candle_body", "is_bullish", "doji",
        "pct_from_52w_high",
        "donchian_20_break",
        "vol_of_vol_20",
    ]


def _legacy_regime_label(df: pd.DataFrame) -> str:
    if len(df) < 50:
        return "unknown"
    feats = compute_features(df)
    latest = feats.iloc[-1]
    vol = latest.get("volatility_20d", 0)
    price_vs_50 = latest.get("price_vs_sma50", 0)
    sma_cross = latest.get("sma_cross_20_50", 0)
    rsi = latest.get("rsi_14", 50)
    if vol > 0.4:
        return "volatile"
    if sma_cross == 1 and price_vs_50 > 0.02 and rsi > 50:
        return "bull"
    if sma_cross == 0 and price_vs_50 < -0.02 and rsi < 50:
        return "bear"
    return "sideways"


def compute_regime(df: pd.DataFrame) -> str:
    """Deprecated wrapper. Production callers use market_regime.label_from_closes.

    Kept for tests and shadow until 2026-11-04.
    """
    old = "unknown"
    try:
        if {"high", "low", "close"}.issubset(df.columns):
            old = _legacy_regime_label(df)
    except Exception:
        old = "unknown"
    try:
        from app.services.qa.feature_flags import is_enabled
        from app.services.market_regime.service import classify_from_prices, shadow_old_label

        if is_enabled("qa_market_regime") and "close" in df.columns:
            prices = [float(x) for x in df["close"].tolist() if x == x]
            if len(prices) >= 2:
                fresh = classify_from_prices(prices, scope="instrument", ticker="LEGACY")
                shadow_old_label(old if old != "unknown" else "sideways", str(fresh["label"]))
                return str(fresh["label"])
    except Exception:
        pass
    return {
        "bull": "trend_up",
        "bear": "trend_down",
        "sideways": "range",
        "volatile": "volatility",
        "unknown": "insufficient",
    }.get(old, old)
