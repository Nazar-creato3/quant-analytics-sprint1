"""Stacking meta-model over ensemble member predictions (LightGBM / logistic)."""
from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from app.core.logging import get_logger
from app.services.ml.model import MODEL_DIR

logger = get_logger(__name__)

STACKING_MODEL_NAME = "forecast_stacking_meta"


@dataclass(frozen=True, slots=True)
class StackingResult:
    expected_return: float
    direction: int
    available: bool
    note: str = ""
    member_weights: tuple[float, ...] = ()


def _sign(ret: float, threshold: float = 0.002) -> int:
    if ret > threshold:
        return 1
    if ret < -threshold:
        return -1
    return 0


class StackingMetaModel:
    """Learn combination of member expected returns → direction/return."""

    def __init__(self, model_name: str = STACKING_MODEL_NAME) -> None:
        self.model_name = model_name
        self._model = None
        self._load()

    def _path(self) -> Path:
        return MODEL_DIR / f"{self.model_name}.pkl"

    def _load(self) -> None:
        path = self._path()
        if not path.exists():
            return
        try:
            with open(path, "rb") as f:
                self._model = pickle.load(f)
        except Exception as exc:
            logger.debug("stacking_model_load_failed", error=str(exc))

    def predict(self, member_returns: Sequence[float]) -> StackingResult:
        x = np.asarray(member_returns, dtype=float).reshape(1, -1)
        if x.size == 0:
            return StackingResult(0.0, 0, False, "no_members")
        if self._model is None:
            # Uniform weighted average fallback (legacy behaviour).
            w = np.ones(x.shape[1]) / x.shape[1]
            ret = float(np.dot(w, x.ravel()))
            return StackingResult(ret, _sign(ret), True, "uniform_average", tuple(w.tolist()))
        try:
            if hasattr(self._model, "predict_proba"):
                proba = self._model.predict_proba(x)[0]
                p_up = float(proba[1]) if len(proba) > 1 else float(proba[0])
                direction = 1 if p_up > 0.55 else (-1 if p_up < 0.45 else 0)
                magnitude = abs(p_up - 0.5) * 2.0
                ret = direction * magnitude * 0.05
                return StackingResult(ret, direction, True, "stacking_meta", ())
            ret = float(self._model.predict(x)[0])
            return StackingResult(ret, _sign(ret), True, "stacking_meta", ())
        except Exception as exc:
            logger.debug("stacking_predict_failed", error=str(exc))
            ret = float(np.mean(x))
            return StackingResult(ret, _sign(ret), True, "stacking_error_mean", ())

    def train(
        self,
        member_matrix: np.ndarray,
        labels: np.ndarray,
        *,
        method: str = "lightgbm",
    ) -> dict[str, float]:
        """Train meta-model. member_matrix shape (n, k), labels in {-1,0,1} or {0,1}."""
        y = np.asarray(labels)
        if set(np.unique(y)).issubset({-1, 0, 1}):
            y_bin = (y > 0).astype(int)
        else:
            y_bin = y.astype(int)
        if method == "logistic":
            from sklearn.linear_model import LogisticRegression

            model = LogisticRegression(max_iter=500)
            model.fit(member_matrix, y_bin)
        else:
            import lightgbm as lgb

            model = lgb.LGBMClassifier(
                n_estimators=80,
                learning_rate=0.05,
                num_leaves=15,
                verbose=-1,
            )
            model.fit(member_matrix, y_bin)
        self._model = model
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        with open(self._path(), "wb") as f:
            pickle.dump(model, f)
        pred = model.predict(member_matrix)
        acc = float(np.mean(pred == y_bin)) if len(y_bin) else 0.5
        return {"train_accuracy": acc, "n": float(len(y_bin))}

    def reload(self) -> None:
        self._model = None
        self._load()


def build_stacking_training_matrix(
    prices: Sequence[float],
    *,
    horizon: int = 5,
    min_history: int = 60,
) -> tuple[np.ndarray, np.ndarray]:
    """Walk-forward member returns (ARIMA/mom/LGBM proxies) → realized direction labels.

    Uses lightweight proxies so training does not require Chronos GPU/CPU budget.
    Matrix columns: [arima_proxy, momentum, lgbm_proxy, nbeats_proxy, chronos_proxy, regime_proxy]
    """
    px = np.asarray(prices, dtype=float)
    rows: list[list[float]] = []
    labels: list[int] = []
    for i in range(min_history, len(px) - horizon):
        hist = px[:i]
        last = float(hist[-1])
        if last <= 0:
            continue
        mom = float(np.mean(hist[-5:]) / max(np.mean(hist[-20:]), 1e-9) - 1.0)
        arima_proxy = float((hist[-1] / max(hist[-min(10, len(hist))], 1e-9)) - 1.0)
        lgbm_proxy = mom * 0.8 + arima_proxy * 0.2
        nbeats_proxy = float((np.mean(hist[-3:]) / max(np.mean(hist[-15:]), 1e-9)) - 1.0)
        chronos_proxy = mom  # stand-in during meta training; live Chronos used at inference
        regime_proxy = float(np.sign(mom) * abs(mom) * 0.5)
        realized = (px[i + horizon - 1] - px[i - 1]) / max(px[i - 1], 1e-9)
        label = 1 if realized > 0.002 else (-1 if realized < -0.002 else 0)
        if label == 0:
            continue
        rows.append([arima_proxy, mom, lgbm_proxy, nbeats_proxy, chronos_proxy, regime_proxy])
        labels.append(label)
    if not rows:
        return np.zeros((0, 6)), np.zeros((0,), dtype=int)
    return np.asarray(rows, dtype=float), np.asarray(labels, dtype=int)


def train_stacking_meta_from_prices(
    prices: Sequence[float],
    *,
    method: str = "lightgbm",
    horizon: int = 5,
) -> dict[str, float | str | bool]:
    """Train + persist stacking meta; returns metrics and artifact path."""
    X, y = build_stacking_training_matrix(prices, horizon=horizon)
    if len(y) < 40:
        return {"ok": False, "reason": "insufficient_samples", "n": float(len(y))}
    meta = get_stacking_meta_model()
    metrics = meta.train(X, y, method=method)
    meta.reload()
    path = meta._path()
    return {
        "ok": True,
        "path": str(path),
        "exists": path.exists(),
        "method": method,
        **metrics,
    }


_META: StackingMetaModel | None = None


def get_stacking_meta_model() -> StackingMetaModel:
    global _META
    if _META is None:
        _META = StackingMetaModel()
    return _META


def reset_stacking_meta_model() -> StackingMetaModel:
    """Force reload after training on disk."""
    global _META
    _META = StackingMetaModel()
    return _META
