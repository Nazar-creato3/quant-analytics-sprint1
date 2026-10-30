"""Fast C.3 diagnosis — 6mo yfinance, no full HierarchyValidationEngine on long series."""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yfinance as yf

from app.services.control_fabric.replay_validation import infer_actual_regime_from_forward_prices
from app.services.forecast.engine import ForecastEngine
from app.services.forecast.types import ForecastDirection, ForecastInputBundle
from app.services.prediction_hierarchy.hierarchy_validation import HierarchyValidationEngine
from app.services.regime.engine import RegimeEngine
from app.services.track_record.calibration_chart import build_track_record_chart_data
from app.services.track_record.reference_series import build_reference_benchmarks
from app.services.track_record.service import TrackRecordService


def _sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


def binary_direction_walkforward(
    prices: list[float],
    volumes: list[float],
    *,
    horizon: int = 1,
    min_history: int = 30,
) -> dict[str, float | int]:
    engine = ForecastEngine()
    hits = total = 0
    for i in range(min_history, len(prices) - horizon):
        hist = prices[: i + 1]
        vols = volumes[: i + 1]
        f = engine.compute_from_inputs(
            ForecastInputBundle(instrument_id=1, prices=hist, volumes=vols)
        )
        pred = _sign(
            1
            if f.signals.momentum_direction == ForecastDirection.BULLISH
            else (-1 if f.signals.momentum_direction == ForecastDirection.BEARISH else 0)
        )
        if pred == 0:
            continue
        actual = _sign((prices[i + horizon] - prices[i]) / max(prices[i], 1e-9))
        if actual == 0:
            continue
        total += 1
        hits += int(pred == actual)
    return {
        "accuracy": round(hits / total, 4) if total else 0.0,
        "n": total,
    }


def regime_match_walkforward(
    prices: list[float],
    *,
    forward_horizon: int = 10,
    min_history: int = 30,
) -> dict[str, float | int]:
    re = RegimeEngine()
    hits = total = 0
    for i in range(min_history - 1, len(prices) - forward_horizon):
        hist = prices[: i + 1]
        fwd = prices[i + 1 : i + 1 + forward_horizon]
        pred = re.classify_instrument(hist).dominant_regime
        actual = infer_actual_regime_from_forward_prices(fwd, regime_engine=re)
        total += 1
        hits += int(pred == actual)
    return {
        "accuracy": round(hits / total, 4) if total else 0.0,
        "n": total,
    }


def quarterly_binary(prices: list[float], volumes: list[float], dates: list[str]) -> dict[str, dict]:
    engine = ForecastEngine()
    buckets: dict[str, list[bool]] = defaultdict(list)
    for i in range(30, len(prices) - 1):
        if i >= len(dates):
            break
        hist = prices[: i + 1]
        f = engine.compute_from_inputs(
            ForecastInputBundle(instrument_id=1, prices=hist, volumes=volumes[: i + 1])
        )
        pred = _sign(
            1
            if f.signals.momentum_direction == ForecastDirection.BULLISH
            else (-1 if f.signals.momentum_direction == ForecastDirection.BEARISH else 0)
        )
        if pred == 0:
            continue
        actual = _sign((prices[i + 1] - prices[i]) / max(prices[i], 1e-9))
        if actual == 0:
            continue
        y, m, _ = dates[i].split("-")
        q = f"{y}-Q{(int(m) - 1) // 3 + 1}"
        buckets[q].append(pred == actual)
    return {q: {"accuracy": round(sum(v) / len(v), 4), "n": len(v)} for q, v in sorted(buckets.items())}


def main() -> None:
    t0 = time.time()
    chart = build_track_record_chart_data()
    tr = TrackRecordService().get_public_summary()
    inst = next(r.accuracy for r in tr.level_accuracy if r.level == "instrument_regime")

    bench = build_reference_benchmarks()[0]
    bench_rep = HierarchyValidationEngine().run(
        instrument_id=10000,
        prices=list(bench.prices),
        volumes=[1.0] * len(bench.prices),
    )
    bench_acc = next(
        la.accuracy for la in bench_rep.level_accuracy if la.level == "instrument_regime"
    )

    report: dict = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runtime_sec": 0,
        "system_metrics": {
            "track_record_public_instrument_regime_acc": round(inst, 4),
            "synthetic_trend_benchmark_regime_acc": round(bench_acc, 4),
            "calibration_chart_live_vs_backtest_gap": chart.live_vs_backtest_gap,
            "calibration_chart_rolling_accuracies": [
                {"window": p.window_days, "acc": p.directional_accuracy}
                for p in chart.rolling_accuracy
            ],
            "note": "directional_accuracy in UI = regime match, not price up/down",
        },
        "symbols": {},
    }

    for sym in ("AAPL", "MSFT", "SPY"):
        hist = yf.Ticker(sym).history(period="6mo", auto_adjust=True)
        prices = [float(x) for x in hist["Close"].tolist()]
        volumes = [float(x) for x in hist["Volume"].tolist()]
        dates = [d.strftime("%Y-%m-%d") for d in hist.index]
        report["symbols"][sym] = {
            "bars": len(prices),
            "date_range": [dates[0], dates[-1]] if dates else [],
            "regime_match_h10": regime_match_walkforward(prices, forward_horizon=10),
            "binary_direction": {
                "h1": binary_direction_walkforward(prices, volumes, horizon=1),
                "h5": binary_direction_walkforward(prices, volumes, horizon=5),
                "h10": binary_direction_walkforward(prices, volumes, horizon=10),
                "h20": binary_direction_walkforward(prices, volumes, horizon=20),
            },
            "quarterly_binary_h1": quarterly_binary(prices, volumes, dates),
        }

    report["runtime_sec"] = round(time.time() - t0, 1)
    out = Path(__file__).resolve().parents[2] / "docs" / "forecast_accuracy_diagnosis_data.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
