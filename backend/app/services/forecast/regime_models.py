"""Regime-specific forecast model training (Step 5)."""
from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from app.core.logging import get_logger
from app.services.forecast.forecast_features import FORECAST_FEATURE_COLUMNS, build_feature_matrix
from app.services.forecast.triple_barrier import TripleBarrierConfig, triple_barrier_labels
from app.services.ml.model import MODEL_DIR
from app.services.regime.engine import RegimeEngine

logger = get_logger(__name__)

REGIME_MODEL_PREFIX = "forecast_regime_"
SUPPORTED_REGIMES = (
    "bullish_trend",
    "bearish_trend",
    "choppy_range",
    "high_volatility_shock",
)


@dataclass(frozen=True, slots=True)
class RegimeModelPrediction:
    expected_return: float
    direction: int
    regime: str
    available: bool
    note: str = ""


class RegimeForecastModels:
    """Per-regime LightGBM instances selected at inference by current regime."""

    def __init__(self) -> None:
        self._models: dict[str, object] = {}
        self._load_all()

    def _model_path(self, regime: str) -> Path:
        return MODEL_DIR / f"{REGIME_MODEL_PREFIX}{regime}.pkl"

    def _load_all(self) -> None:
        for regime in SUPPORTED_REGIMES:
            path = self._model_path(regime)
            if path.exists():
                try:
                    with open(path, "rb") as f:
                        self._models[regime] = pickle.load(f)
                except Exception as exc:
                    logger.debug("Regime model load failed", regime=regime, error=str(exc))

    def predict(
        self,
        prices: Sequence[float],
        *,
        horizon: int = 10,
        regime_label: str | None = None,
    ) -> RegimeModelPrediction:
        if len(prices) < 30:
            return RegimeModelPrediction(0.0, 0, regime_label or "unknown", False)

        engine = RegimeEngine()
        regime = regime_label or engine.classify_instrument(list(prices)).dominant_regime
        model = self._models.get(regime)
        if model is None:
            return RegimeModelPrediction(0.0, 0, regime, False, "no_regime_model")

        from app.services.forecast.forecast_features import build_forecast_feature_row

        features = build_forecast_feature_row(prices, regime_label=regime)
        X = np.array([[features[c] for c in FORECAST_FEATURE_COLUMNS]])
        try:
            proba = model.predict_proba(X)[0]  # type: ignore[union-attr]
            p_up = float(proba[1]) if len(proba) > 1 else float(proba[0])
            direction = 1 if p_up > 0.55 else (-1 if p_up < 0.45 else 0)
            magnitude = abs(p_up - 0.5) * 2.0
            ret = direction * magnitude * 0.05 * (horizon / 10.0)
            return RegimeModelPrediction(ret, direction, regime, True, f"regime_{regime}")
        except Exception as exc:
            return RegimeModelPrediction(0.0, 0, regime, False, str(exc))


def train_regime_models(
    closes: Sequence[float],
    *,
    min_history: int = 30,
    min_samples_per_regime: int = 30,
) -> dict[str, dict[str, float]]:
    """Train separate LightGBM per regime on triple-barrier labels."""
    import lightgbm as lgb

    labels = triple_barrier_labels(closes, config=TripleBarrierConfig(max_holding_days=10))
    engine = RegimeEngine()
    regime_at: list[str] = []
    for i in range(len(closes)):
        if i < min_history:
            regime_at.append("choppy_range")
        else:
            regime_at.append(engine.classify_instrument(list(closes[: i + 1])).dominant_regime)

    df = build_feature_matrix(closes, regime_labels=regime_at, min_history=min_history)
    metrics: dict[str, dict[str, float]] = {}

    for regime in SUPPORTED_REGIMES:
        indices = [
            j
            for j in range(len(df))
            if regime_at[min_history + j] == regime and labels[min_history + j] != 0
        ]
        if len(indices) < min_samples_per_regime:
            metrics[regime] = {"skipped": True, "n": len(indices)}
            continue

        X = df.iloc[indices].values
        y = np.array([labels[min_history + j] for j in indices])
        model = lgb.LGBMClassifier(
            n_estimators=100,
            learning_rate=0.05,
            max_depth=4,
            random_state=42,
            verbose=-1,
        )
        model.fit(X, y)
        path = MODEL_DIR / f"{REGIME_MODEL_PREFIX}{regime}.pkl"
        with open(path, "wb") as f:
            pickle.dump(model, f)
        acc = float((model.predict(X) == y).mean())
        metrics[regime] = {"accuracy": acc, "n": len(y), "skipped": False}

    return metrics


_models: RegimeForecastModels | None = None


def get_regime_forecast_models() -> RegimeForecastModels:
    global _models
    if _models is None:
        _models = RegimeForecastModels()
    return _models
