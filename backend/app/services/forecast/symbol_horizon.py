"""Per-symbol forecast horizon selection via purged walk-forward CV."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from app.services.forecast.direction_accuracy import direction_from_return
from app.services.forecast.ensemble import EnsembleForecastEngine, _momentum_forecast
from app.services.forecast.purged_cv import evaluate_purged_accuracy
from app.services.ml.model import MODEL_DIR

DEFAULT_HORIZON_CANDIDATES: tuple[int, ...] = (1, 5, 10, 20)
MIN_HISTORY_BARS = 30
HORIZON_CACHE_PATH = MODEL_DIR / "symbol_horizons.json"

# LightGBM/triple-barrier is trained at ~10d. Serving those signs as a 1-day
# call for names whose live 1d track record is at or below chance is dishonest.
# AAPL h=1d ~47% binary (FORECAST_ACCURACY_CRISIS_DIAGNOSIS); MSFT/SPY similar.
UNTRUSTED_1D_SYMBOLS: frozenset[str] = frozenset({"AAPL", "MSFT", "SPY"})
MIN_TRUSTED_HORIZON_DAYS = 5
# Don't pick h=1 from purged CV unless it clearly beats a coin flip.
SHORT_HORIZON_MIN_PURGED_ACCURACY = 0.55

# Benchmark fallbacks (docs/forecast_horizon_benchmark.json).
_BENCHMARK_BEST_HORIZON: dict[str, int] = {
    "AAPL": 10,
    "MSFT": 10,
    "SPY": 10,
    "GLD": 10,
    "QQQ": 10,
}


@dataclass(frozen=True, slots=True)
class HorizonSelection:
    symbol: str
    horizon_days: int
    purged_cv_accuracy: float
    purged_cv_n: int
    candidates: tuple[tuple[int, float, int], ...]


def _clamp_untrusted_short_horizon(symbol: str, horizon: int) -> int:
    """Refuse h=1d for symbols with below-chance 1d live track records."""
    sym = symbol.upper()
    if horizon >= MIN_TRUSTED_HORIZON_DAYS:
        return int(horizon)
    if sym in UNTRUSTED_1D_SYMBOLS:
        return int(_BENCHMARK_BEST_HORIZON.get(sym, 10))
    return int(horizon)


def _load_horizon_cache() -> dict[str, int]:
    if not HORIZON_CACHE_PATH.exists():
        return dict(_BENCHMARK_BEST_HORIZON)
    try:
        raw = json.loads(HORIZON_CACHE_PATH.read_text(encoding="utf-8"))
        return {str(k).upper(): int(v) for k, v in raw.items()}
    except Exception:
        return dict(_BENCHMARK_BEST_HORIZON)


def _save_horizon_cache(horizons: dict[str, int]) -> None:
    HORIZON_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    HORIZON_CACHE_PATH.write_text(
        json.dumps(horizons, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _walk_forward_signs(
    prices: Sequence[float],
    *,
    predictor,
    horizon: int,
    min_history: int = MIN_HISTORY_BARS,
) -> tuple[list[int], list[int]]:
    labels: list[int] = []
    preds: list[int] = []
    last = len(prices) - horizon
    for i in range(min_history, last):
        history = prices[: i + 1]
        pred_ret = predictor(history)
        pred_sign = direction_from_return(pred_ret)
        actual_ret = (prices[i + horizon] - prices[i]) / max(prices[i], 1e-9)
        actual_sign = direction_from_return(actual_ret)
        labels.append(actual_sign)
        preds.append(pred_sign)
    return labels, preds


def evaluate_symbol_horizon_momentum(
    prices: Sequence[float],
    *,
    horizon: int,
    min_history: int = MIN_HISTORY_BARS,
) -> tuple[float, int]:
    if len(prices) < min_history + horizon + 10:
        return 0.5, 0
    labels, preds = _walk_forward_signs(
        prices,
        predictor=lambda p: _momentum_forecast(p, horizon)[0],
        horizon=horizon,
        min_history=min_history,
    )
    purged = evaluate_purged_accuracy(labels, preds, label_horizon=horizon)
    return purged.accuracy, purged.n


def evaluate_symbol_horizon_ensemble(
    prices: Sequence[float],
    *,
    symbol: str,
    horizon: int,
    min_history: int = MIN_HISTORY_BARS,
) -> tuple[float, int]:
    if len(prices) < min_history + horizon + 10:
        return 0.5, 0
    engine = EnsembleForecastEngine()
    labels: list[int] = []
    preds: list[int] = []
    last = len(prices) - horizon
    for i in range(min_history, last):
        history = prices[: i + 1]
        forecast = engine.compute(history, symbol=symbol.upper(), horizon_days=horizon)
        pred_sign = int(forecast.direction_consensus)
        actual_ret = (prices[i + horizon] - prices[i]) / max(prices[i], 1e-9)
        actual_sign = direction_from_return(actual_ret)
        labels.append(actual_sign)
        preds.append(pred_sign)
    purged = evaluate_purged_accuracy(labels, preds, label_horizon=horizon)
    return purged.accuracy, purged.n


def select_best_horizon(
    prices: Sequence[float],
    *,
    symbol: str,
    horizons: Sequence[int] = DEFAULT_HORIZON_CANDIDATES,
    min_history: int = MIN_HISTORY_BARS,
    min_purged_n: int = 20,
    use_ensemble: bool = False,
) -> HorizonSelection:
    """Pick the horizon with highest purged-CV accuracy for this symbol."""
    sym = symbol.upper()
    candidates: list[tuple[int, float, int]] = []
    for horizon in horizons:
        if use_ensemble:
            acc, n = evaluate_symbol_horizon_ensemble(
                prices,
                symbol=sym,
                horizon=int(horizon),
                min_history=min_history,
            )
        else:
            acc, n = evaluate_symbol_horizon_momentum(
                prices,
                horizon=int(horizon),
                min_history=min_history,
            )
        if n >= min_purged_n:
            if int(horizon) <= 1 and (
                acc < SHORT_HORIZON_MIN_PURGED_ACCURACY or sym in UNTRUSTED_1D_SYMBOLS
            ):
                continue
            candidates.append((int(horizon), acc, n))

    if not candidates:
        fallback = _clamp_untrusted_short_horizon(
            sym, _BENCHMARK_BEST_HORIZON.get(sym, 10)
        )
        return HorizonSelection(
            symbol=sym,
            horizon_days=fallback,
            purged_cv_accuracy=0.5,
            purged_cv_n=0,
            candidates=(),
        )

    best = max(candidates, key=lambda row: (row[1], -abs(row[0] - 10)))
    chosen = _clamp_untrusted_short_horizon(sym, best[0])
    if chosen != best[0]:
        alt = next((row for row in candidates if row[0] == chosen), None)
        if alt is not None:
            best = alt
        else:
            best = (chosen, best[1], best[2])
    return HorizonSelection(
        symbol=sym,
        horizon_days=int(best[0]),
        purged_cv_accuracy=best[1],
        purged_cv_n=best[2],
        candidates=tuple(candidates),
    )


def refresh_symbol_horizon_cache(
    symbol_prices: dict[str, Sequence[float]],
    *,
    use_ensemble: bool = True,
) -> dict[str, int]:
    """Recompute and persist per-symbol horizons (called from weekly retrain)."""
    cache = _load_horizon_cache()
    for symbol, prices in symbol_prices.items():
        selection = select_best_horizon(
            prices,
            symbol=symbol,
            use_ensemble=use_ensemble,
        )
        cache[symbol.upper()] = _clamp_untrusted_short_horizon(
            symbol, selection.horizon_days
        )
    _save_horizon_cache(cache)
    return cache


def horizon_for_symbol(
    prices: Sequence[float],
    *,
    symbol: str,
    horizons: Sequence[int] = DEFAULT_HORIZON_CANDIDATES,
) -> int:
    """Return cached or benchmark horizon for live inference paths.

    Inline purged-CV selection is reserved for offline retrain — running it per
    request (e.g. GLD without cache) added multi-second latency to /forecast.
    """
    sym = symbol.upper()
    cached = _load_horizon_cache().get(sym)
    if cached is not None:
        return _clamp_untrusted_short_horizon(sym, cached)
    return _clamp_untrusted_short_horizon(sym, _BENCHMARK_BEST_HORIZON.get(sym, 10))
