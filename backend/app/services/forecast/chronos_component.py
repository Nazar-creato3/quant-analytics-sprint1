"""Amazon Chronos (Apache-2.0) ensemble component with graceful fallback."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from app.core.logging import get_logger

logger = get_logger(__name__)

MIN_CHRONOS_HISTORY = 40
CHRONOS_MODEL_ID = "amazon/chronos-t5-tiny"


@dataclass(frozen=True, slots=True)
class ChronosForecastResult:
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


def _momentum_fallback(prices: Sequence[float], horizon: int) -> ChronosForecastResult:
    if len(prices) < 20:
        return ChronosForecastResult(0.0, 0, False, 0.5, "insufficient_history")
    short = float(np.mean(prices[-5:]))
    long = float(np.mean(prices[-20:]))
    mom = (short - long) / max(long, 1e-9)
    scaled = mom * (horizon / 10.0)
    return ChronosForecastResult(scaled, _sign(scaled), True, 0.5, "chronos_unavailable_momentum")


class ChronosForecastComponent:
    """Chronos foundation model member for the forecast ensemble."""

    def __init__(self) -> None:
        self._pipeline: Any | None = None
        self._load_failed = False

    def _get_pipeline(self) -> Any | None:
        if self._load_failed:
            return None
        if self._pipeline is not None:
            return self._pipeline
        try:
            import os
            from contextlib import contextmanager
            from pathlib import Path

            import torch
            from chronos import ChronosPipeline

            # Container user may have HOME=/nonexistent; keep HF weights on model volume.
            hf_home = os.environ.get("HF_HOME") or "/app/models/hf_cache"
            Path(hf_home).mkdir(parents=True, exist_ok=True)
            os.environ.setdefault("HF_HOME", hf_home)
            os.environ.setdefault("HUGGINGFACE_HUB_CACHE", hf_home)

            cache_hit = any(Path(hf_home).glob("**/models--amazon--chronos-t5-tiny/**"))
            local_only = cache_hit or os.environ.get("CHRONOS_LOCAL_FILES_ONLY", "").lower() in {
                "1",
                "true",
                "yes",
            }

            @contextmanager
            def _without_http_proxy():
                keys = (
                    "HTTP_PROXY",
                    "HTTPS_PROXY",
                    "http_proxy",
                    "https_proxy",
                    "ALL_PROXY",
                    "all_proxy",
                    "FOREIGN_HTTPS_PROXY",
                )
                saved = {k: os.environ.pop(k, None) for k in keys}
                try:
                    yield
                finally:
                    for k, v in saved.items():
                        if v is not None:
                            os.environ[k] = v

            with _without_http_proxy():
                self._pipeline = ChronosPipeline.from_pretrained(
                    CHRONOS_MODEL_ID,
                    device_map="cpu",
                    torch_dtype=torch.float32,
                    local_files_only=local_only,
                )
            return self._pipeline
        except Exception as exc:
            self._load_failed = True
            logger.warning("Chronos pipeline unavailable", error=str(exc)[:300])
            return None

    def predict(self, prices: Sequence[float], *, horizon: int = 10) -> ChronosForecastResult:
        if len(prices) < MIN_CHRONOS_HISTORY:
            return ChronosForecastResult(0.0, 0, False, 0.5, "insufficient_history")
        pipeline = self._get_pipeline()
        if pipeline is None:
            return _momentum_fallback(prices, horizon)
        try:
            import torch

            context = torch.tensor(list(prices)[-min(len(prices), 512) :], dtype=torch.float32)
            pred_len = min(max(horizon, 1), 32)
            forecast = pipeline.predict(context, prediction_length=pred_len)
            median = forecast[0].median(dim=0).values
            last = float(prices[-1])
            future = float(median[-1].item())
            if last <= 0:
                return _momentum_fallback(prices, horizon)
            ret = (future - last) / last
            scaled = ret * (horizon / max(pred_len, 1))
            return ChronosForecastResult(float(scaled), _sign(scaled), True, 0.5, "chronos_t5_tiny")
        except Exception as exc:
            logger.debug("Chronos forecast failed", error=str(exc))
            return _momentum_fallback(prices, horizon)

    def rolling_accuracy(self, prices: list[float], *, horizon: int = 5, window: int = 40) -> float:
        if len(prices) < window + horizon + 5:
            return 0.5
        hits = 0
        total = 0
        for i in range(window, len(prices) - horizon, max(1, horizon)):
            pred = self.predict(prices[:i], horizon=horizon)
            if not pred.available or pred.direction == 0:
                continue
            realized = (prices[i + horizon - 1] - prices[i - 1]) / max(prices[i - 1], 1e-9)
            realized_dir = 1 if realized > 0.002 else (-1 if realized < -0.002 else 0)
            if realized_dir == 0:
                continue
            hits += int(pred.direction == realized_dir)
            total += 1
        return hits / total if total else 0.5


_COMPONENT: ChronosForecastComponent | None = None


def get_chronos_component() -> ChronosForecastComponent:
    global _COMPONENT
    if _COMPONENT is None:
        _COMPONENT = ChronosForecastComponent()
    return _COMPONENT
