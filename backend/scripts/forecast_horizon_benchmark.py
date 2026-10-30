"""STEP 2 — systematic horizon benchmark over longest available history."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.forecast.validation_runner import report_to_dict, run_symbol_validation


def _fetch_yfinance(symbol: str, days: int = 504) -> tuple[list[float], list[float]]:
    import yfinance as yf

    hist = yf.Ticker(symbol).history(period=f"{days}d", auto_adjust=True)
    if hist.empty:
        raise ValueError(f"no data for {symbol}")
    prices = [float(v) for v in hist["Close"].tolist()]
    volumes = [float(v) for v in hist["Volume"].tolist()]
    return prices, volumes


def main() -> None:
    symbols = ["AAPL", "MSFT", "SPY"]
    horizons = [1, 5, 10, 20]
    report: dict[str, object] = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "history_days": 504,
        "methodology": "walk-forward + purged CV + triple-barrier labels",
        "symbols": {},
    }

    for symbol in symbols:
        try:
            prices, volumes = _fetch_yfinance(symbol)
            validation = run_symbol_validation(symbol, prices, volumes, horizons=horizons)
            report["symbols"][symbol] = report_to_dict(validation)
        except Exception as exc:
            report["symbols"][symbol] = {"error": str(exc)}

    out = Path(__file__).resolve().parents[2] / "docs" / "forecast_horizon_benchmark.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nWrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
