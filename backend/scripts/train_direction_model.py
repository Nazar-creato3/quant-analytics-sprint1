#!/usr/bin/env python3
"""
Train the LightGBM direction classifier used by SHAP explainability.

Usage (from backend/):
  python scripts/train_direction_model.py
  python scripts/train_direction_model.py --tickers AAPL MSFT AMZN --days 730
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import pandas as pd

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

DEFAULT_TICKERS = [
    "AAPL",
    "MSFT",
    "AMZN",
    "GOOGL",
    "META",
    "NVDA",
    "SPY",
    "QQQ",
    "JPM",
    "XOM",
    "UNH",
    "HD",
]


def _download_ohlcv(symbol: str, *, days: int) -> pd.DataFrame:
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    hist = ticker.history(period=f"{days}d", auto_adjust=True)
    if hist.empty:
        raise RuntimeError(f"No OHLCV history for {symbol}")
    hist = hist.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    return hist[["open", "high", "low", "close", "volume"]].copy()


def _synthetic_ohlcv(symbol: str, *, days: int, seed: int) -> pd.DataFrame:
    import random

    rng = random.Random(hash(symbol) % 2**31 + seed)
    price = 80.0 + (hash(symbol) % 200)
    rows = []
    for _ in range(days):
        shock = rng.gauss(0.0004, 0.012)
        price = max(1.0, price * math.exp(shock))
        vol = max(100_000, rng.gauss(1_500_000, 400_000))
        rows.append(
            {
                "open": price * (1 - 0.002),
                "high": price * (1 + abs(rng.gauss(0, 0.008))),
                "low": price * (1 - abs(rng.gauss(0, 0.008))),
                "close": price,
                "volume": vol,
            }
        )
    df = pd.DataFrame(rows)
    df["symbol"] = symbol
    return df


def build_training_frame(tickers: list[str], *, days: int, synthetic: bool = False) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for symbol in tickers:
        try:
            if synthetic:
                df = _synthetic_ohlcv(symbol, days=days, seed=42)
            else:
                df = _download_ohlcv(symbol, days=days)
                df["symbol"] = symbol
            frames.append(df)
            print(f"  {symbol}: {len(df)} bars")
        except Exception as exc:
            print(f"  {symbol}: SKIP ({exc})")
    if not frames:
        raise RuntimeError("No training data — check network / yfinance access or use --synthetic")
    return pd.concat(frames, ignore_index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train direction_lgbm for SHAP explainability")
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument("--days", type=int, default=730, help="History window per ticker")
    parser.add_argument("--model-name", default="direction_lgbm")
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Use synthetic OHLCV (offline / CI); omit for live yfinance download",
    )
    args = parser.parse_args()

    mode = "synthetic" if args.synthetic else "yfinance"
    print(f"Downloading OHLCV for {len(args.tickers)} tickers ({args.days}d, {mode})...")
    combined = build_training_frame(args.tickers, days=args.days, synthetic=args.synthetic)
    print(f"Combined rows: {len(combined)}")

    from app.services.ml.features import compute_features
    from app.services.ml.model import MODEL_DIR, train_direction_model

    featured = compute_features(combined.drop(columns=["symbol"], errors="ignore"))
    metrics = train_direction_model(
        featured,
        model_name=args.model_name,
        already_featured=True,
    )

    model_path = MODEL_DIR / f"{args.model_name}.pkl"
    calib_path = MODEL_DIR / f"{args.model_name}_calibrator.pkl"
    print("Training complete:")
    for key, val in metrics.items():
        print(f"  {key}: {val}")
    print(f"Model:      {model_path} ({model_path.stat().st_size // 1024} KB)")
    print(f"Calibrator: {calib_path} ({calib_path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
