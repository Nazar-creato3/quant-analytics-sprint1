"""Unified forecast validation runner — Steps 1-2 reporting with purged CV."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Sequence

from app.services.forecast.cross_sectional import evaluate_cross_sectional_vs_absolute
from app.services.forecast.engine import ForecastEngine
from app.services.forecast.ensemble import EnsembleForecastEngine, _momentum_forecast
from app.services.forecast.purged_cv import evaluate_purged_accuracy
from app.services.forecast.triple_barrier import TripleBarrierConfig, triple_barrier_labels
from app.services.forecast.types import ForecastDirection, ForecastInputBundle


@dataclass
class HorizonAccuracy:
    horizon_days: int
    accuracy: float
    n: int
    purged_cv_accuracy: float
    purged_cv_n: int
    triple_barrier_accuracy: float
    triple_barrier_n: int


@dataclass
class SymbolValidationReport:
    symbol: str
    bars: int
    horizons: list[HorizonAccuracy]
    cross_sectional_accuracy: float
    cross_sectional_n: int
    absolute_cross_sectional_accuracy: float
    absolute_cross_sectional_n: int


def _sign_from_direction(direction: ForecastDirection) -> int:
    if direction == ForecastDirection.BULLISH:
        return 1
    if direction == ForecastDirection.BEARISH:
        return -1
    return 0


def walk_forward_binary(
    prices: list[float],
    volumes: list[float] | None,
    *,
    horizon: int,
    min_history: int = 30,
) -> tuple[list[int], list[int]]:
    """Return (labels, predictions) for purged CV evaluation."""
    engine = ForecastEngine()
    labels: list[int] = []
    preds: list[int] = []
    last = len(prices) - horizon
    for i in range(min_history, last):
        history = prices[: i + 1]
        bundle = ForecastInputBundle(instrument_id=1, prices=history, volumes=volumes)
        forecast = engine.compute_from_inputs(bundle)
        pred_sign = _sign_from_direction(forecast.signals.momentum_direction)
        actual_ret = (prices[i + horizon] - prices[i]) / max(prices[i], 1e-9)
        actual_sign = 1 if actual_ret > 0.002 else (-1 if actual_ret < -0.002 else 0)
        labels.append(actual_sign)
        preds.append(pred_sign)
    return labels, preds


def evaluate_horizon(
    prices: list[float],
    volumes: list[float] | None,
    *,
    horizon: int,
    min_history: int = 30,
) -> HorizonAccuracy:
    labels, preds = walk_forward_binary(prices, volumes, horizon=horizon, min_history=min_history)
    hits = sum(1 for a, p in zip(labels, preds) if a != 0 and p != 0 and a == p)
    total = sum(1 for a, p in zip(labels, preds) if a != 0 and p != 0)
    acc = hits / total if total else 0.0

    purged = evaluate_purged_accuracy(labels, preds, label_horizon=horizon)

    tb_labels = triple_barrier_labels(
        prices,
        config=TripleBarrierConfig(max_holding_days=horizon),
    )
    tb_preds = [0] * len(prices)
    engine = ForecastEngine()
    for i in range(min_history, len(prices) - horizon):
        bundle = ForecastInputBundle(instrument_id=1, prices=prices[: i + 1])
        forecast = engine.compute_from_inputs(bundle)
        tb_preds[i] = _sign_from_direction(forecast.signals.momentum_direction)
    tb_purged = evaluate_purged_accuracy(
        [tb_labels[i] for i in range(min_history, len(prices) - horizon)],
        [tb_preds[i] for i in range(min_history, len(prices) - horizon)],
        label_horizon=horizon,
    )

    return HorizonAccuracy(
        horizon_days=horizon,
        accuracy=round(acc, 4),
        n=total,
        purged_cv_accuracy=round(purged.accuracy, 4),
        purged_cv_n=purged.n,
        triple_barrier_accuracy=round(tb_purged.accuracy, 4),
        triple_barrier_n=tb_purged.n,
    )


def run_symbol_validation(
    symbol: str,
    prices: list[float],
    volumes: list[float] | None,
    *,
    horizons: Sequence[int] = (1, 5, 10, 20),
) -> SymbolValidationReport:
    horizon_results = [
        evaluate_horizon(prices, volumes, horizon=h) for h in horizons
    ]
    cs = evaluate_cross_sectional_vs_absolute(
        {symbol: prices},
        lambda p: _momentum_forecast(p, 10)[0],
        horizon=10,
    )
    return SymbolValidationReport(
        symbol=symbol,
        bars=len(prices),
        horizons=horizon_results,
        cross_sectional_accuracy=round(cs.accuracy, 4),
        cross_sectional_n=cs.n,
        absolute_cross_sectional_accuracy=round(cs.absolute_accuracy, 4),
        absolute_cross_sectional_n=cs.n,
    )


def report_to_dict(report: SymbolValidationReport) -> dict:
    return {
        "symbol": report.symbol,
        "bars": report.bars,
        "horizons": [asdict(h) for h in report.horizons],
        "cross_sectional": {
            "ranking_accuracy": report.cross_sectional_accuracy,
            "n": report.cross_sectional_n,
            "absolute_accuracy": report.absolute_cross_sectional_accuracy,
            "absolute_n": report.absolute_cross_sectional_n,
        },
    }


def run_shap_validation_report(
    prices: list[float],
    *,
    symbol: str = "BENCHMARK",
    news_sentiment: float = 0.0,
    order_book_imbalance: float = 0.0,
) -> dict:
    """SHAP feature-importance on held-out validation (Step 3)."""
    from app.services.forecast.shap_diagnostics import run_forecast_shap_diagnostics

    enrichments = [
        {"news_sentiment": news_sentiment, "order_book_imbalance": order_book_imbalance}
        for _ in prices
    ]
    return run_forecast_shap_diagnostics(prices, symbol=symbol, enrichments=enrichments).to_dict()
