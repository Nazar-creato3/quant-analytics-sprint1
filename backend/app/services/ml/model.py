"""
ML inference engine.
Uses LightGBM for direction classification with isotonic calibration.
Falls back to deterministic rule-based scoring when model is unavailable.
"""
from __future__ import annotations

import os
import pickle
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.core.config import settings
from app.core.logging import get_logger
from app.services.ml.features import compute_features, get_feature_columns

logger = get_logger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = Path(os.getenv("MODEL_DIR", str(_BACKEND_ROOT / "models")))
MODEL_DIR.mkdir(parents=True, exist_ok=True)
_MODEL_SEED_DIR = Path(os.getenv("MODEL_SEED_DIR", "/app/model_seeds"))
if not _MODEL_SEED_DIR.is_dir():
    _alt_seed = _BACKEND_ROOT / "model_seeds"
    if _alt_seed.is_dir():
        _MODEL_SEED_DIR = _alt_seed


def _seed_models_from_image() -> None:
    """Copy baked-in model artifacts into MODEL_DIR when the runtime volume is empty."""
    if not _MODEL_SEED_DIR.is_dir():
        return
    for src in _MODEL_SEED_DIR.glob("*.pkl"):
        dst = MODEL_DIR / src.name
        if not dst.exists():
            try:
                shutil.copy2(src, dst)
                logger.info("Seeded model artifact", file=src.name, target=str(dst))
            except OSError as exc:
                logger.warning("Failed to seed model artifact", file=src.name, error=str(exc))


@dataclass
class ModelPrediction:
    """Output of the inference engine for a single ticker."""
    ticker: str
    direction: str          # "long" | "short" | "neutral"
    confidence: float       # 0–1 (calibrated probability)
    raw_score: float        # uncalibrated
    signal_strength: float  # 0–1
    features_used: dict[str, float]
    model_version: str
    is_fallback: bool = False


class DirectionClassifier:
    """
    Wraps a LightGBM + calibrator pipeline.
    Falls back to technical rule scoring if no model file exists.
    """

    def __init__(self, model_name: str = "direction_lgbm") -> None:
        self.model_name = model_name
        self._model: Any = None
        self._calibrator: Any = None
        self._version: str = "fallback"
        self._load_model()

    def _load_model(self) -> None:
        _seed_models_from_image()
        model_path = MODEL_DIR / f"{self.model_name}.pkl"
        calib_path = MODEL_DIR / f"{self.model_name}_calibrator.pkl"
        if model_path.exists():
            try:
                with open(model_path, "rb") as f:
                    self._model = pickle.load(f)
                if calib_path.exists():
                    with open(calib_path, "rb") as f:
                        self._calibrator = pickle.load(f)
                self._version = model_path.stat().st_mtime.__str__()[:10]
                logger.info("Model loaded", model=self.model_name, version=self._version)
            except Exception as exc:
                logger.warning("Failed to load model, using fallback", error=str(exc))
                self._model = None
        else:
            logger.info("No model file found, using rule-based fallback", model=self.model_name)

    def predict(self, df: pd.DataFrame, ticker: str) -> ModelPrediction:
        """Run inference on the latest bar of a feature DataFrame."""
        df_feat = compute_features(df)
        return self.predict_from_features(df_feat, ticker)

    def predict_from_features(self, df_feat: pd.DataFrame, ticker: str) -> ModelPrediction:
        """Run inference when features are already computed (avoids duplicate work)."""
        features = self._extract_features(df_feat)

        if self._model is not None:
            return self._ml_predict(features, ticker)
        return self._rule_based_predict(features, ticker, df_feat)

    def _extract_features(self, df: pd.DataFrame) -> dict[str, float]:
        feature_cols = get_feature_columns()
        available = [c for c in feature_cols if c in df.columns]
        if df.empty:
            return {col: 0.0 for col in available}
        row = df.iloc[-1]
        return {col: float(row[col]) if not pd.isna(row[col]) else 0.0 for col in available}

    def _ml_predict(self, features: dict[str, float], ticker: str) -> ModelPrediction:
        """LightGBM + calibrator inference."""
        import lightgbm as lgb

        feature_cols = get_feature_columns()
        # Features are only ever appended to the canonical list, so a model trained on an
        # older, shorter list reads its first n columns. A model wider than the list cannot
        # be fed correctly: use the rule-based path instead of failing every ticker.
        n_model = int(getattr(self._model, "n_features_in_", len(feature_cols)) or len(feature_cols))
        if n_model > len(feature_cols):
            logger.warning("Model expects more features than computed; rule-based fallback", expected=n_model, have=len(feature_cols))
            return self._rule_based_predict(features, ticker, None)
        if n_model < len(feature_cols) and not getattr(self, "_width_logged", False):
            logger.info("Model trained on an older feature list; using its first columns", model_features=n_model, current=len(feature_cols))
            self._width_logged = True
        cols = feature_cols[:n_model]
        X = np.array([[features.get(col, 0.0) for col in cols]])
        names = getattr(self._model, "feature_names_in_", None)
        if names is not None and len(names) == n_model:
            # Same column names as at fit time: no sklearn warning per prediction.
            X = pd.DataFrame(X, columns=list(names))

        raw_prob = float(self._model.predict_proba(X)[0, 1])

        # Calibrate
        if self._calibrator is not None:
            try:
                calibrated = float(self._calibrator.predict_proba(X)[0, 1])
            except ValueError as exc:
                logger.warning("Calibrator rejected features; using raw probability", error=str(exc)[:120])
                calibrated = raw_prob
        else:
            calibrated = raw_prob

        direction, strength = self._prob_to_signal(calibrated)
        # Confidence = probability of the predicted direction
        direction_confidence = calibrated if direction == "long" else (1.0 - calibrated if direction == "short" else calibrated)

        return ModelPrediction(
            ticker=ticker,
            direction=direction,
            confidence=direction_confidence,
            raw_score=raw_prob,
            signal_strength=strength,
            features_used=features,
            model_version=self._version,
            is_fallback=False,
        )

    def _rule_based_predict(
        self, features: dict[str, float], ticker: str, df: pd.DataFrame
    ) -> ModelPrediction:
        """
        Deterministic technical rule scoring when no ML model is available.
        Returns confidence in [0.4, 0.75] range — never overconfident.
        """
        score = 0.0
        count = 0

        # RSI
        rsi = features.get("rsi_14", 50)
        if rsi < 30:
            score += 0.7  # oversold → long bias
        elif rsi > 70:
            score += 0.3  # overbought → short bias
        else:
            score += 0.5
        count += 1

        # MACD
        if features.get("macd_bullish", 0):
            score += 0.6
        else:
            score += 0.4
        count += 1

        # Trend
        if features.get("sma_cross_5_20", 0) and features.get("price_vs_sma20", 0) > 0:
            score += 0.65
        elif not features.get("sma_cross_5_20", 1) and features.get("price_vs_sma20", 0) < 0:
            score += 0.35
        else:
            score += 0.5
        count += 1

        # Volume confirmation
        if features.get("volume_ratio", 1) > 1.3 and features.get("is_bullish", 0):
            score += 0.65
        elif features.get("volume_ratio", 1) > 1.3 and not features.get("is_bullish", 0):
            score += 0.35
        else:
            score += 0.5
        count += 1

        # Momentum
        roc5 = features.get("roc_5", 0)
        if roc5 > 2:
            score += 0.65
        elif roc5 < -2:
            score += 0.35
        else:
            score += 0.5
        count += 1

        raw_prob = score / count
        # Push away from neutral band so fallback still produces directional signals
        if raw_prob > 0.5:
            raw_prob = min(0.45 + (raw_prob - 0.5) * 1.4, 0.78)
        else:
            raw_prob = max(0.55 - (0.5 - raw_prob) * 1.4, 0.22)
        calibrated = float(np.clip(raw_prob, 0.32, 0.78))

        direction, strength = self._prob_to_signal(calibrated)
        direction_confidence = calibrated if direction == "long" else (1.0 - calibrated if direction == "short" else calibrated)
        return ModelPrediction(
            ticker=ticker,
            direction=direction,
            confidence=direction_confidence,
            raw_score=raw_prob,
            signal_strength=strength,
            features_used=features,
            model_version="rule_based_v1",
            is_fallback=True,
        )

    @staticmethod
    def _prob_to_signal(prob: float) -> tuple[str, float]:
        """Convert a probability to direction + strength."""
        # Narrow neutral band — calibrated models often cluster at ~0.50–0.51.
        if abs(prob - 0.5) <= 0.003:
            return "neutral", 0.0
        if prob > 0.5:
            return "long", min((prob - 0.5) * 2, 1.0)
        return "short", min((0.5 - prob) * 2, 1.0)


# ── Model Training ────────────────────────────────────────────────────────────

def train_direction_model(
    df: pd.DataFrame,
    model_name: str = "direction_lgbm",
    target_col: str = "target_1d",
    test_size: float = 0.2,
    already_featured: bool = False,
) -> dict[str, float]:
    """
    Train a LightGBM direction classifier on historical features.
    Saves model and calibrator to MODEL_DIR.

    Returns: dict of evaluation metrics
    """
    import lightgbm as lgb
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.metrics import accuracy_score, log_loss, roc_auc_score
    from sklearn.model_selection import TimeSeriesSplit

    df_feat = df if already_featured else compute_features(df)
    feature_cols = [c for c in get_feature_columns() if c in df_feat.columns]
    subset = feature_cols + ([target_col] if target_col in df_feat.columns else [])
    df_feat = df_feat.dropna(subset=subset)
    if df_feat.empty:
        raise ValueError("No training samples after feature computation — need more history")
    X = df_feat[feature_cols].values
    y = df_feat[target_col].values

    from app.services.alpha.nested_cpcv import Candidate, nested_cpcv_select
    from app.services.quant_desk.purged_cv import purged_walk_forward

    def _fit_predict(Xtr, ytr, Xte, params: dict):
        clf = lgb.LGBMClassifier(
            n_estimators=int(params.get("n_estimators", 180)),
            learning_rate=0.05,
            max_depth=int(params.get("max_depth", 5)),
            num_leaves=int(params.get("num_leaves", 24)),
            min_child_samples=20,
            subsample=0.8,
            colsample_bytree=0.8,
            class_weight="balanced",
            random_state=42,
            verbose=-1,
        )
        clf.fit(Xtr, ytr)
        return clf.predict(Xte)

    selection = nested_cpcv_select(
        np.asarray(X),
        np.asarray(y),
        (
            Candidate("shallow", {"n_estimators": 120, "num_leaves": 12, "max_depth": 3}),
            Candidate("mid", {"n_estimators": 220, "num_leaves": 24, "max_depth": 5}),
            Candidate("deep", {"n_estimators": 300, "num_leaves": 31, "max_depth": 6}),
        ),
        _fit_predict,
        label_horizon=1 if "1d" in target_col else 5,
        n_groups=6 if len(X) >= 80 else 4,
        n_test_groups=2 if len(X) >= 80 else 1,
    )
    wp = selection.winner.params

    folds = purged_walk_forward(len(X), n_splits=3, embargo=max(3, int(round(5 * test_size * 10))))
    if folds:
        train_i, test_i = folds[-1]
        X_train, X_test = X[train_i], X[test_i]
        y_train, y_test = y[train_i], y[test_i]
    else:
        split = int(len(X) * (1 - test_size))
        X_train, X_test = X[:split], X[split:]
        y_train, y_test = y[:split], y[split:]

    model = lgb.LGBMClassifier(
        n_estimators=int(wp.get("n_estimators", 220)),
        learning_rate=0.05,
        max_depth=int(wp.get("max_depth", 5)),
        num_leaves=int(wp.get("num_leaves", 24)),
        min_child_samples=20,
        subsample=0.8,
        colsample_bytree=0.8,
        class_weight="balanced",
        random_state=42,
        verbose=-1,
    )
    model.fit(X_train, y_train)

    # Calibrate on test set (skip if single-class — rare on small synthetic samples)
    calibrator = None
    if len(set(y_test.tolist())) >= 2:
        calibrator = CalibratedClassifierCV(model, method="isotonic", cv="prefit")
        calibrator.fit(X_test, y_test)

    # Evaluate
    y_pred = model.predict(X_test)
    if calibrator is not None:
        proba = calibrator.predict_proba(X_test)
        y_prob = proba[:, 1] if proba.shape[1] > 1 else proba[:, 0]
    else:
        proba = model.predict_proba(X_test)
        y_prob = proba[:, 1] if proba.shape[1] > 1 else proba[:, 0]
    metrics = {
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "auc": float(roc_auc_score(y_test, y_prob)),
        "log_loss": float(log_loss(y_test, y_prob)),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "cv_method": selection.method,
        "nested_cpcv_accuracy": float(selection.outer_accuracy),
        "nested_winner": selection.winner.name,
        "label_recipe": "triple_barrier+meta_label" if "barrier" in target_col else target_col,
    }
    logger.info("Model trained", metrics=metrics)

    # Save
    with open(MODEL_DIR / f"{model_name}.pkl", "wb") as f:
        pickle.dump(model, f)
    if calibrator is not None:
        with open(MODEL_DIR / f"{model_name}_calibrator.pkl", "wb") as f:
            pickle.dump(calibrator, f)

    return metrics


# ── Singleton ─────────────────────────────────────────────────────────────────

_classifier: DirectionClassifier | None = None


def get_classifier() -> DirectionClassifier:
    global _classifier
    if _classifier is None:
        _classifier = DirectionClassifier()
    return _classifier
