#!/usr/bin/env python3
"""Post-retrain verification on prod (no secrets)."""
from __future__ import annotations

import json

from app.services.forecast.symbol_horizon import HORIZON_CACHE_PATH, horizon_for_symbol
from app.services.ml.model import MODEL_DIR


def main() -> None:
    symbols = ["AAPL", "MSFT", "SPY"]
    print("model_dir:", MODEL_DIR)
    for sym in symbols:
        pkl = MODEL_DIR / f"forecast_direction_lgbm_{sym}.pkl"
        exists = pkl.exists()
        print(f"{sym}_pkl:", exists, "size=", pkl.stat().st_size if exists else 0)
        print(f"{sym}_horizon:", horizon_for_symbol([], symbol=sym))
    print("horizon_cache:", HORIZON_CACHE_PATH.exists())
    if HORIZON_CACHE_PATH.exists():
        print(json.loads(HORIZON_CACHE_PATH.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
