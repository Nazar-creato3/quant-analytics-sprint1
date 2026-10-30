"""C.3 forecast accuracy crisis diagnosis — run from backend/ with venv active."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

# Allow `python scripts/forecast_accuracy_diagnosis.py` from backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from app.services.control_fabric.replay_validation import infer_actual_regime_from_forward_prices
from app.services.forecast.distribution import build_forecast_distribution
from app.services.forecast.engine import ForecastEngine
from app.services.forecast.ensemble import EnsembleForecastEngine, _rolling_directional_accuracy
from app.services.forecast.signals import compute_short_term_momentum
from app.services.forecast.types import ForecastInputBundle, ForecastDirection
from app.services.prediction_hierarchy.hierarchy_validation import HierarchyValidationEngine
from app.services.regime.engine import RegimeEngine
from app.services.track_record.calibration_chart import build_track_record_chart_data
from app.services.track_record.reference_series import build_reference_benchmarks
from app.services.track_record.service import TrackRecordService


def _fetch_yfinance(symbol: str, days: int = 504) -> tuple[list[float], list[float], list[str]]:
    try:
        import yfinance as yf
    except ImportError:
        raise SystemExit("yfinance required: pip install yfinance")

    ticker = yf.Ticker(symbol)
    hist = ticker.history(period=f"{days}d", auto_adjust=True)
    if hist.empty:
        raise ValueError(f"no data for {symbol}")
    dates = [d.strftime("%Y-%m-%d") for d in hist.index]
    prices = [float(v) for v in hist["Close"].tolist()]
    volumes = [float(v) for v in hist["Volume"].tolist()]
    return prices, volumes, dates


def _sign(x: float, threshold: float = 0.0) -> int:
    if x > threshold:
        return 1
    if x < -threshold:
        return -1
    return 0


@dataclass
class WalkForwardResult:
    accuracy: float
    n: int
    neutral_skipped: int = 0


def walk_forward_binary_direction(
    prices: list[float],
    volumes: list[float] | None,
    *,
    horizon: int = 1,
    min_history: int = 30,
    use_neutral: bool = False,
) -> WalkForwardResult:
    """True binary direction accuracy using ForecastEngine momentum pipeline."""
    engine = ForecastEngine()
    hits = 0
    total = 0
    neutral_skipped = 0
    last = len(prices) - horizon
    for i in range(min_history, last):
        history = prices[: i + 1]
        vols = volumes[: i + 1] if volumes else None
        bundle = ForecastInputBundle(
            instrument_id=1,
            prices=history,
            volumes=vols,
        )
        forecast = engine.compute_from_inputs(bundle)
        dist = build_forecast_distribution(
            prices=history,
            momentum_score=forecast.signals.short_term_momentum,
            direction=forecast.signals.momentum_direction,
        )
        pred_sign = _sign(
            forecast.signals.momentum_direction.value == "bullish"
            and 1
            or (-1 if forecast.signals.momentum_direction.value == "bearish" else 0)
        )
        if dist.low_confidence or dist.insufficient_data or pred_sign == 0:
            if not use_neutral:
                neutral_skipped += 1
                continue
        actual_ret = (prices[i + horizon] - prices[i]) / max(prices[i], 1e-9)
        actual_sign = _sign(actual_ret)
        if actual_sign == 0:
            continue
        if pred_sign == 0 and use_neutral:
            neutral_skipped += 1
            continue
        total += 1
        if pred_sign == actual_sign:
            hits += 1
    return WalkForwardResult(
        accuracy=round(hits / total, 4) if total else 0.0,
        n=total,
        neutral_skipped=neutral_skipped,
    )


def walk_forward_regime_match(
    prices: list[float],
    volumes: list[float] | None,
    *,
    forward_horizon: int = 10,
    min_history: int = 30,
) -> WalkForwardResult:
    """What HierarchyValidationEngine actually measures as 'directional_accuracy'."""
    regime_engine = RegimeEngine()
    hits = 0
    total = 0
    last = len(prices) - forward_horizon
    for i in range(min_history - 1, last):
        history = prices[: i + 1]
        forward = prices[i + 1 : i + 1 + forward_horizon]
        pred = regime_engine.classify_instrument(history).dominant_regime
        actual = infer_actual_regime_from_forward_prices(forward, regime_engine=regime_engine)
        total += 1
        if pred == actual:
            hits += 1
    return WalkForwardResult(accuracy=round(hits / total, 4) if total else 0.0, n=total)


def breakdown_by_regime(
    prices: list[float],
    *,
    horizon: int = 1,
    min_history: int = 30,
) -> dict[str, dict[str, float]]:
    engine = ForecastEngine()
    regime_engine = RegimeEngine()
    buckets: dict[str, list[bool]] = defaultdict(list)
    last = len(prices) - horizon
    for i in range(min_history, last):
        history = prices[: i + 1]
        bundle = ForecastInputBundle(instrument_id=1, prices=history)
        forecast = engine.compute_from_inputs(bundle)
        pred_sign = _sign(
            1
            if forecast.signals.momentum_direction == ForecastDirection.BULLISH
            else (-1 if forecast.signals.momentum_direction == ForecastDirection.BEARISH else 0)
        )
        if pred_sign == 0:
            continue
        actual_ret = (prices[i + horizon] - prices[i]) / max(prices[i], 1e-9)
        actual_sign = _sign(actual_ret)
        if actual_sign == 0:
            continue
        regime = regime_engine.classify_instrument(history).dominant_regime
        buckets[regime].append(pred_sign == actual_sign)
    return {
        regime: {
            "accuracy": round(sum(v) / len(v), 4),
            "n": len(v),
        }
        for regime, v in sorted(buckets.items())
    }


def breakdown_by_quarter(
    prices: list[float],
    dates: list[str],
    *,
    horizon: int = 1,
    min_history: int = 30,
) -> dict[str, dict[str, float]]:
    engine = ForecastEngine()
    buckets: dict[str, list[bool]] = defaultdict(list)
    last = len(prices) - horizon
    for i in range(min_history, last):
        if i >= len(dates):
            break
        history = prices[: i + 1]
        bundle = ForecastInputBundle(instrument_id=1, prices=history)
        forecast = engine.compute_from_inputs(bundle)
        pred_sign = _sign(
            1
            if forecast.signals.momentum_direction == ForecastDirection.BULLISH
            else (-1 if forecast.signals.momentum_direction == ForecastDirection.BEARISH else 0)
        )
        if pred_sign == 0:
            continue
        actual_ret = (prices[i + horizon] - prices[i]) / max(prices[i], 1e-9)
        actual_sign = _sign(actual_ret)
        if actual_sign == 0:
            continue
        q = dates[i][:7]  # YYYY-MM proxy; aggregate monthly for finer collapse detection
        buckets[q].append(pred_sign == actual_sign)
    # Collapse to quarterly
    quarterly: dict[str, list[bool]] = defaultdict(list)
    for month, vals in buckets.items():
        y, m = month.split("-")
        q = f"{y}-Q{(int(m) - 1) // 3 + 1}"
        quarterly[q].extend(vals)
    return {
        q: {"accuracy": round(sum(v) / len(v), 4), "n": len(v)}
        for q, v in sorted(quarterly.items())
    }


def random_split_leakage_demo(prices: list[float], *, horizon: int = 1) -> dict[str, float]:
    """Compare chronological walk-forward vs random 70/30 split (leakage-prone)."""
    engine = ForecastEngine()
    n = len(prices)
    indices = list(range(30, n - horizon))
    rng = np.random.default_rng(0)
    shuffled = list(indices)
    rng.shuffle(shuffled)
    split = int(len(shuffled) * 0.7)
    train_idx = set(shuffled[:split])
    test_idx = shuffled[split:]

    def acc(idxs: list[int]) -> float:
        hits = total = 0
        for i in idxs:
            history = prices[: i + 1]
            bundle = ForecastInputBundle(instrument_id=1, prices=history)
            forecast = engine.compute_from_inputs(bundle)
            pred_sign = _sign(
                1
                if forecast.signals.momentum_direction == ForecastDirection.BULLISH
                else (-1 if forecast.signals.momentum_direction == ForecastDirection.BEARISH else 0)
            )
            if pred_sign == 0:
                continue
            actual_ret = (prices[i + horizon] - prices[i]) / max(prices[i], 1e-9)
            actual_sign = _sign(actual_ret)
            if actual_sign == 0:
                continue
            total += 1
            if pred_sign == actual_sign:
                hits += 1
        return round(hits / total, 4) if total else 0.0

    return {
        "walk_forward_chronological": acc(indices),
        "random_70_30_split": acc(test_idx),
        "random_split_inflation": round(
            acc(test_idx) - acc(indices), 4
        ),
    }


def main() -> None:
    symbols = ["AAPL", "MSFT", "SPY", "BTC-USD"]
    horizons = [1, 5, 10, 20]
    report: dict[str, object] = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "methodology_notes": [],
        "symbols": {},
        "track_record_system": {},
        "validation_engine_audit": {},
    }

    # Track record / backtest headline numbers from codebase
    chart = build_track_record_chart_data()
    tr = TrackRecordService().get_public_summary()
    inst_level = next(
        (r.accuracy for r in tr.level_accuracy if r.level == "instrument_regime"),
        None,
    )
    report["track_record_system"] = {
        "public_instrument_regime_accuracy": inst_level,
        "calibration_chart_rolling_windows": [
            {"window_days": p.window_days, "regime_match_accuracy": p.regime_match_accuracy}
            for p in chart.rolling_accuracy[:6]
        ],
        "live_vs_backtest_gap_field": chart.live_vs_backtest_gap,
        "drift_flag": chart.drift_flag,
        "benchmark_source": "synthetic reference_series (NOT real tickers)",
        "benchmark_keys": [b.key for b in build_reference_benchmarks()],
    }

    # HierarchyValidationEngine on synthetic benchmark
    h_engine = HierarchyValidationEngine()
    bench = build_reference_benchmarks()[0]
    bench_report = h_engine.run(
        instrument_id=10000,
        prices=list(bench.prices),
        volumes=[1.0] * len(bench.prices),
    )
    inst_acc = next(la.accuracy for la in bench_report.level_accuracy if la.level == "instrument_regime")
    report["validation_engine_audit"] = {
        "uses_walk_forward": True,
        "forward_horizon_days": 10,
        "metric_is_regime_match_not_price_direction": True,
        "synthetic_benchmark_instrument_regime_accuracy": round(inst_acc, 4),
        "hardcoded_signals_in_validation_loop": True,
        "hardcoded_momentum": 0.4,
    }

    for symbol in symbols:
        try:
            prices, volumes, dates = _fetch_yfinance(symbol)
        except Exception as exc:
            report["symbols"][symbol] = {"error": str(exc)}
            continue

        sym_data: dict[str, object] = {
            "bars": len(prices),
            "date_range": [dates[0], dates[-1]] if dates else [],
        }

        sym_data["regime_match_accuracy_h10"] = asdict(
            walk_forward_regime_match(prices, volumes, forward_horizon=10)
        )

        h_report = None
        try:
            h_report = h_engine.run(
                instrument_id=1,
                prices=prices,
                volumes=volumes,
            )
            sym_data["hierarchy_validation_instrument_regime"] = round(
                next(la.accuracy for la in h_report.level_accuracy if la.level == "instrument_regime"),
                4,
            )
            sym_data["hierarchy_rolling_windows"] = [
                m.to_dict() for m in h_report.rolling_window_metrics
            ]
        except ValueError as exc:
            sym_data["hierarchy_validation_error"] = str(exc)

        sym_data["binary_direction_by_horizon"] = {}
        for h in horizons:
            wf = walk_forward_binary_direction(prices, volumes, horizon=h)
            sym_data["binary_direction_by_horizon"][f"{h}d"] = asdict(wf)

        sym_data["regime_breakdown_h1"] = breakdown_by_regime(prices, horizon=1)
        sym_data["quarterly_breakdown_h1"] = breakdown_by_quarter(prices, dates, horizon=1)
        sym_data["random_vs_walkforward_h1"] = random_split_leakage_demo(prices, horizon=1)

        ens = EnsembleForecastEngine()
        sym_data["ensemble_rolling_acc"] = {
            m.family.value: round(m.recent_accuracy, 4)
            for m in ens.compute(prices, momentum_score=0.55).component_models
        }

        sym_data["coin_flip_baseline"] = 0.5
        report["symbols"][symbol] = sym_data

    report["methodology_notes"] = [
        "Backtest UI 'directional_accuracy' = regime label match over forward window, not up/down.",
        "Track record aggregates synthetic trend/cycle series, not AAPL OHLCV.",
        "live_vs_backtest_gap in calibration_chart is avg calibration error, not live minus backtest.",
        "model_drift live_accuracy uses maneuver PnL, not forecast direction resolution.",
        "HierarchyValidationEngine validation loop uses hardcoded ForecastSignals (momentum=0.4).",
        "Binary direction uses walk-forward ForecastEngine momentum — no random split in production.",
    ]

    out_path = Path(__file__).resolve().parents[2] / "docs" / "forecast_accuracy_diagnosis_data.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nWrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
