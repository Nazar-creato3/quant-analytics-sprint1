"""N-BEATS deep forecasting component via Darts (with EMA fallback)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from app.core.logging import get_logger

logger = get_logger(__name__)

MIN_NBEATS_HISTORY = 60
NBEATS_INPUT_CHUNK = 30
NBEATS_OUTPUT_CHUNK = 5


@dataclass(frozen=True, slots=True)
class NBeatsForecastResult:
    expected_return: float
    direction: int
    available: bool
    recent_accuracy: float
    note: str = ""


def _sign(ret: float, threshold: float = 0.002) -> int:
    if ret > threshold:
        return 1
    if ret < -threshold:
        return -1
    return 0


def _ema_fallback_forecast(prices: Sequence[float], horizon: int) -> NBeatsForecastResult:
    if len(prices) < 15:
        return NBeatsForecastResult(0.0, 0, False, 0.5, "insufficient_history")
    short = np.mean(prices[-5:])
    long = np.mean(prices[-20:]) if len(prices) >= 20 else np.mean(prices)
    mom = (short - long) / max(long, 1e-9)
    scaled = mom * (horizon / 10.0)
    return NBeatsForecastResult(scaled, _sign(scaled), True, 0.5, "ema_fallback")


_DARTS_OK: bool | None = None


def _darts_available() -> bool:
    """Darts N-BEATS needs torch. Without it every import attempt re-imports darts (tens of
    seconds on the server, plus an ERROR log line) and still fails: check once per process."""
    global _DARTS_OK
    if _DARTS_OK is None:
        import importlib.util

        _DARTS_OK = importlib.util.find_spec("torch") is not None and importlib.util.find_spec("darts") is not None
        if not _DARTS_OK:
            logger.info("N-BEATS disabled: torch/darts not installed, EMA fallback used")
    return _DARTS_OK


def _nbeats_forecast(prices: Sequence[float], horizon: int) -> NBeatsForecastResult:
    global _DARTS_OK
    if not _darts_available():
        return _ema_fallback_forecast(prices, horizon)
    try:
        from darts import TimeSeries
        from darts.models import NBEATSModel

        log_prices = np.log(np.maximum(np.asarray(prices, dtype=float), 1e-9))
        series = TimeSeries.from_values(log_prices)

        input_chunk = min(NBEATS_INPUT_CHUNK, len(log_prices) - 10)
        output_chunk = min(NBEATS_OUTPUT_CHUNK, horizon)
        if input_chunk < 20:
            return _ema_fallback_forecast(prices, horizon)

        model = NBEATSModel(
            input_chunk_length=input_chunk,
            output_chunk_length=output_chunk,
            n_epochs=3,
            random_state=42,
            pl_trainer_kwargs={"enable_progress_bar": False, "logger": False},
        )
        model.fit(series[-input_chunk * 3 :])
        forecast = model.predict(output_chunk)
        pred_log = float(forecast.values()[-1, 0])
        current_log = float(log_prices[-1])
        ret = np.exp(pred_log - current_log) - 1.0
        scaled = float(ret) * (horizon / max(output_chunk, 1))
        return NBeatsForecastResult(scaled, _sign(scaled), True, 0.5, "darts_nbeats")
    except ImportError:
        _DARTS_OK = False
        return _ema_fallback_forecast(prices, horizon)
    except Exception as exc:
        logger.debug("N-BEATS forecast failed", error=str(exc))
        return _ema_fallback_forecast(prices, horizon)


class NBeatsForecastComponent:
    """Darts N-BEATS with walk-forward accuracy tracking."""

    def predict(self, prices: Sequence[float], *, horizon: int = 10) -> NBeatsForecastResult:
        if len(prices) < MIN_NBEATS_HISTORY:
            return NBeatsForecastResult(0.0, 0, False, 0.5, "insufficient_history")
        return _nbeats_forecast(list(prices), horizon)

    def rolling_accuracy(
        self,
        prices: Sequence[float],
        *,
        horizon: int = 5,
        window: int = 30,
    ) -> float:
        """Walk-forward accuracy — uses EMA proxy for speed in weighting loop."""
        if len(prices) < window + horizon + 10:
            return 0.5
        hits = total = 0
        step = max(5, (len(prices) - window - horizon) // 8)
        for i in range(window, len(prices) - horizon, step):
            pred = _ema_fallback_forecast(prices[:i], horizon)
            if pred.direction == 0:
                continue
            actual = (prices[i + horizon] - prices[i]) / max(prices[i], 1e-9)
            total += 1
            if _sign(actual) == pred.direction:
                hits += 1
        return hits / total if total else 0.5


_component: NBeatsForecastComponent | None = None


def get_nbeats_component() -> NBeatsForecastComponent:
    global _component
    if _component is None:
        _component = NBeatsForecastComponent()
    return _component
