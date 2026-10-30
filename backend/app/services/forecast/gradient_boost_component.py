"""LightGBM forecast component trained on triple-barrier labels with purged CV."""
from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from app.core.logging import get_logger
from app.services.forecast.forecast_features import (
    FORECAST_FEATURE_COLUMNS,
    build_forecast_feature_row,
)
from app.services.forecast.purged_cv import (
    evaluate_cpcv_accuracy,
    evaluate_purged_accuracy,
    purged_kfold_splits,
)
from app.services.forecast.triple_barrier import TripleBarrierConfig, triple_barrier_labels
from app.services.ml.model import MODEL_DIR

logger = get_logger(__name__)

FORECAST_LGBM_MODEL = "forecast_direction_lgbm"
STUB_PREDICTION_STD_THRESHOLD = 0.01


@dataclass(frozen=True, slots=True)
class GradientBoostForecastResult:
    expected_return: float
    direction: int
    available: bool
    recent_accuracy: float
    note: str = ""
    beat_probability: float = 0.5
    accepted: bool = True


@dataclass(frozen=True, slots=True)
class LgbmValidationReport:
    prediction_std: float
    is_stub: bool
    purged_cv_accuracy: float
    purged_cv_n: int
    top_features: tuple[tuple[str, float], ...]
    cpcv_accuracy: float = 0.5
    cpcv_n: int = 0


def _sign(ret: float, threshold: float = 0.002) -> int:
    if ret > threshold:
        return 1
    if ret < -threshold:
        return -1
    return 0


def model_name_for_symbol(symbol: str | None, horizon: int = 20) -> str:
    base = f"{FORECAST_LGBM_MODEL}_{symbol.strip().upper()}" if symbol else FORECAST_LGBM_MODEL
    h = int(horizon)
    if h == 20:
        return base
    return f"{base}_h{h}"


def _unwrap_lgbm(obj):
    if isinstance(obj, dict) and obj.get("model") is not None:
        return obj["model"], obj
    return obj, None


def validate_trained_lgbm(
    model,
    X: np.ndarray,
    y: np.ndarray,
    *,
    label_horizon: int = 10,
) -> LgbmValidationReport:
    """Check that predictions vary with features and report importances."""
    model, _bundle = _unwrap_lgbm(model)
    proba = model.predict_proba(X)
    p_up = proba[:, 1] if proba.shape[1] > 1 else proba[:, 0]
    pred_std = float(np.std(p_up))
    importances = getattr(model, "feature_importances_", np.zeros(X.shape[1]))
    names = FORECAST_FEATURE_COLUMNS
    if _bundle and _bundle.get("columns"):
        names = tuple(_bundle["columns"])
    if len(names) != len(importances):
        names = tuple(f"f{i}" for i in range(len(importances)))
    ranked = sorted(
        zip(names, importances.tolist()),
        key=lambda pair: pair[1],
        reverse=True,
    )
    preds = model.predict(X)
    y_list = y.tolist()
    pred_list = preds.tolist()
    purged = evaluate_purged_accuracy(y_list, pred_list, label_horizon=label_horizon)
    cpcv = evaluate_cpcv_accuracy(y_list, pred_list, label_horizon=label_horizon)
    return LgbmValidationReport(
        prediction_std=pred_std,
        is_stub=pred_std < STUB_PREDICTION_STD_THRESHOLD,
        purged_cv_accuracy=purged.accuracy,
        purged_cv_n=purged.n,
        top_features=tuple((name, float(score)) for name, score in ranked[:5]),
        cpcv_accuracy=cpcv.accuracy,
        cpcv_n=cpcv.n,
    )


class GradientBoostForecastComponent:
    """Trained LightGBM replacing confidence-threshold heuristic."""

    def __init__(self, model_name: str = FORECAST_LGBM_MODEL) -> None:
        self.model_name = model_name
        self._models: dict[str, object] = {}
        self._load(model_name)

    def _load(self, model_name: str) -> None:
        path = MODEL_DIR / f"{model_name}.pkl"
        if path.exists():
            try:
                with open(path, "rb") as f:
                    self._models[model_name] = pickle.load(f)
            except Exception as exc:
                logger.debug("Forecast LightGBM load failed", model=model_name, error=str(exc))

    def _resolve_model(self, symbol: str | None, horizon: int = 20):
        if symbol:
            sym_name = model_name_for_symbol(symbol, horizon=horizon)
            if sym_name not in self._models:
                self._load(sym_name)
            model = self._models.get(sym_name)
            if model is not None:
                return model, sym_name
            if int(horizon) != 20:
                fallback = model_name_for_symbol(symbol, horizon=20)
                if fallback not in self._models:
                    self._load(fallback)
                model = self._models.get(fallback)
                if model is not None:
                    return model, fallback
        if self.model_name not in self._models:
            self._load(self.model_name)
        return self._models.get(self.model_name), self.model_name

    def _load_named(self, name: str):
        if name not in self._models:
            self._load(name)
        return self._models.get(name), name

    def predict(
        self,
        prices: Sequence[float],
        *,
        symbol: str | None = None,
        horizon: int = 10,
        regime_label: str = "choppy_range",
        sector_relative_strength: float = 0.0,
        order_book_imbalance: float = 0.0,
        news_sentiment: float = 0.0,
        extras: dict[str, float] | None = None,
        volumes: Sequence[float] | None = None,
        highs: Sequence[float] | None = None,
        lows: Sequence[float] | None = None,
        benchmark: Sequence[float] | None = None,
    ) -> GradientBoostForecastResult:
        if len(prices) < 30:
            return GradientBoostForecastResult(0.0, 0, False, 0.5, "insufficient_history")

        from app.services.forecast.cs_cache import load_cs_features

        cs = load_cs_features(symbol or "")
        merged = {**cs, **(extras or {})}
        features = build_forecast_feature_row(
            prices,
            regime_label=regime_label,
            sector_relative_strength=sector_relative_strength,
            order_book_imbalance=0.0,
            news_sentiment=0.0,
            extras=merged,
            volumes=volumes,
            highs=highs,
            lows=lows,
            benchmark=benchmark,
            allow_snapshot_fundamentals=False,
        )
        # Only 20- and 60-session models exist: horizons 1, 5 and 21 all use the 20-session
        # model and return the same probability. The UI shows that one horizon only.
        model_h = 60 if int(horizon) >= 45 else 20
        raw, model_key = self._resolve_model(symbol, horizon=model_h)
        model, bundle = _unwrap_lgbm(raw)
        columns = tuple((bundle or {}).get("columns") or FORECAST_FEATURE_COLUMNS)
        X = np.array([[features.get(c, 0.0) for c in columns]])
        mom = features["returns_5d"] * 0.6 + features["returns_20d"] * 0.4
        if features.get("excess_ret_21"):
            mom = 0.5 * mom + 0.5 * float(features["excess_ret_21"])
        p_mom = float(1.0 / (1.0 + np.exp(-8.0 * mom)))
        p_sym, acc_sym, note = None, False, "untrained"
        if model is not None:
            try:
                n_in = int(getattr(model, "n_features_in_", X.shape[1]))
                if X.shape[1] == n_in:
                    proba = model.predict_proba(X)[0]
                    p_sym = float(proba[1]) if len(proba) > 1 else float(proba[0])
                    acc_sym = True if bundle is None else bool(bundle.get("accepted", True))
                    note = f"lightgbm:{model_key}"
            except Exception as exc:
                logger.debug("symbol LightGBM failed", error=str(exc))

        p_panel, acc_panel = None, False
        try:
            from app.services.forecast.panel_train import panel_model_name

            raw_p, _ = self._load_named(panel_model_name(model_h))
            panel, pbundle = _unwrap_lgbm(raw_p)
            if panel is not None:
                pcols = tuple((pbundle or {}).get("columns") or FORECAST_FEATURE_COLUMNS)
                Xp = np.array([[features.get(c, 0.0) for c in pcols]])
                if Xp.shape[1] == int(getattr(panel, "n_features_in_", Xp.shape[1])):
                    pp = panel.predict_proba(Xp)[0]
                    p_panel = float(pp[1]) if len(pp) > 1 else float(pp[0])
                    acc_panel = True if pbundle is None else bool(pbundle.get("accepted", True))
                    note = f"{note}+panel"
        except Exception as exc:
            logger.debug("panel LightGBM failed", error=str(exc))

        if p_sym is None and p_panel is None:
            scaled = mom * (horizon / 10.0)
            return GradientBoostForecastResult(
                scaled, _sign(scaled), True, 0.5, "untrained_fallback_momentum", p_mom, False
            )
        if p_sym is None:
            p_up = p_panel if p_panel is not None else p_mom
            accepted = acc_panel
        elif p_panel is None:
            p_up = p_sym
            accepted = acc_sym
        else:
            w_panel = 0.55 if acc_panel else 0.35
            w_sym = 0.45 if acc_sym else 0.25
            p_up = (w_sym * p_sym + w_panel * p_panel) / (w_sym + w_panel)
            accepted = acc_sym or acc_panel
        if not accepted:
            p_up = 0.55 * p_mom + 0.45 * p_up
        direction = 1 if p_up > 0.55 else (-1 if p_up < 0.45 else 0)
        magnitude = abs(p_up - 0.5) * 2.0
        ret = direction * magnitude * 0.05 * (horizon / 10.0)
        return GradientBoostForecastResult(
            ret, direction, True, 0.5, note, beat_probability=p_up, accepted=accepted
        )

    def rolling_accuracy(
        self,
        prices: Sequence[float],
        *,
        horizon: int = 5,
        window: int = 20,
        symbol: str | None = None,
    ) -> float:
        if len(prices) < window + horizon + 10:
            return 0.5
        hits = total = 0
        for i in range(window, len(prices) - horizon):
            pred = self.predict(prices[:i], horizon=horizon, symbol=symbol)
            if not pred.available or pred.direction == 0:
                continue
            actual = (prices[i + horizon] - prices[i]) / max(prices[i], 1e-9)
            if _sign(actual) == pred.direction:
                hits += 1
            total += 1
        return hits / total if total else 0.5


def _adaptive_estimators(n_obs: int, n_feat: int) -> int:
    ratio = n_obs / max(n_feat, 1)
    if n_obs >= 2000 or ratio >= 8:
        return 360
    if n_obs >= 400 and ratio >= 4:
        return 280
    return 180


def train_forecast_lgbm(
    closes: Sequence[float],
    *,
    symbol: str | None = None,
    highs: Sequence[float] | None = None,
    lows: Sequence[float] | None = None,
    model_name: str | None = None,
    min_history: int = 30,
    news_sentiment: float = 0.0,
    order_book_imbalance: float = 0.0,
    benchmark_closes: Sequence[float] | None = None,
    extras: dict[str, float] | None = None,
    horizon: int = 20,
    volumes: Sequence[float] | None = None,
    dates: Sequence[str] | None = None,
) -> dict[str, float | str | int | bool]:
    """Train LightGBM on primary TB+meta labels (excess only if TB is too thin)."""
    import lightgbm as lgb

    from app.services.alpha.labels import primary_labels
    from app.services.alpha.nested_cpcv import Candidate, nested_cpcv_select
    from app.services.forecast.cost_model import round_trip_cost_return
    from app.services.forecast.excess_labels import excess_direction_labels
    from app.services.forecast.forecast_features import build_feature_matrix

    resolved_name = model_name or model_name_for_symbol(symbol, horizon=horizon)
    global _component
    prim = primary_labels(
        closes, highs=highs, lows=lows, horizon=horizon, volumes=volumes
    )
    labels = list(prim.side)
    labeled = [x for x in labels if x != 0]
    label_kind = prim.recipe
    if len(labeled) < 40 or len(set(labeled)) < 2:
        labels = excess_direction_labels(
            closes,
            benchmark_closes,
            horizon=horizon,
            cost_return=round_trip_cost_return(symbol or ""),
        )
        labeled = [x for x in labels if x != 0]
        if len(labeled) < 40 or len(set(labeled)) < 2:
            labels = triple_barrier_labels(
                closes,
                highs=highs,
                lows=lows,
                config=TripleBarrierConfig(max_holding_days=min(horizon, 10)),
            )
            label_kind = "triple_barrier_fallback"
        else:
            label_kind = f"excess_{horizon}_fallback"

    aligned_dates = list(dates) if dates and len(dates) == len(closes) else None
    df = build_feature_matrix(
        closes,
        min_history=min_history,
        volumes=volumes,
        highs=highs,
        lows=lows,
        benchmark=benchmark_closes,
        allow_snapshot_fundamentals=False,
        symbol=symbol,
        dates=aligned_dates,
    )
    if df.empty:
        raise ValueError("Insufficient samples for forecast LightGBM training")

    y = np.array(labels[min_history : min_history + len(df)])
    mask = y != 0
    X = df.values[mask]
    y = y[mask]
    if len(y) < 50:
        raise ValueError(f"Too few labeled samples: {len(y)}")

    n_estimators = _adaptive_estimators(len(y), X.shape[1])
    from app.services.forecast.drift import should_skip_retrain

    resolved_path = MODEL_DIR / f"{resolved_name}.pkl"
    if should_skip_retrain(closes, artifact_exists=resolved_path.is_file()):
        return {
            "model_name": resolved_name,
            "skipped_no_drift": True,
            "n_train": int(len(y)),
            "label": label_kind,
        }

    def _fit_xy(Xtr, ytr, n_est: int, num_leaves: int, max_depth: int):
        clf = lgb.LGBMClassifier(
            n_estimators=n_est,
            learning_rate=0.05,
            max_depth=max_depth,
            num_leaves=num_leaves,
            min_child_samples=15,
            subsample=0.8,
            colsample_bytree=0.8,
            class_weight="balanced",
            random_state=42,
            verbose=-1,
        )
        clf.fit(Xtr, ytr)
        return clf

    def _fit_predict(Xtr, ytr, Xte, params: dict):
        clf = _fit_xy(
            Xtr,
            ytr,
            int(params.get("n_estimators", n_estimators)),
            int(params.get("num_leaves", 24)),
            int(params.get("max_depth", 5)),
        )
        return np.asarray(clf.predict(Xte))

    from app.services.alpha.nested_cpcv import default_lgbm_candidates

    candidates = default_lgbm_candidates()
    n_groups, n_test = (6, 2) if len(y) >= 80 else (4, 1)
    selection = nested_cpcv_select(
        X,
        y,
        candidates,
        _fit_predict,
        label_horizon=horizon,
        n_groups=n_groups,
        n_test_groups=n_test,
    )
    wp = selection.winner.params
    n_estimators = int(wp.get("n_estimators", n_estimators))
    model = _fit_xy(X, y, n_estimators, int(wp.get("num_leaves", 24)), int(wp.get("max_depth", 5)))
    preds = model.predict(X)
    validation = validate_trained_lgbm(model, X, y, label_horizon=horizon)
    accepted = (not validation.is_stub) and (
        validation.purged_cv_n < 20 or validation.purged_cv_accuracy >= 0.52
    )
    if not accepted:
        logger.warning(
            "Forecast LightGBM nested CPCV winner still weak",
            symbol=symbol or "global",
            winner=selection.winner.name,
            nested_acc=selection.outer_accuracy,
            purged_cv_accuracy=validation.purged_cv_accuracy,
            accepted=accepted,
        )

    path = MODEL_DIR / f"{resolved_name}.pkl"
    sidecar = MODEL_DIR / f"{resolved_name}.cv.json"
    from app.services.forecast.last_good import should_replace_artifact, write_cv_sidecar

    if path.is_file() and not should_replace_artifact(
        sidecar,
        new_cv=float(validation.purged_cv_accuracy),
        new_n=int(validation.purged_cv_n),
    ):
        kept_last_good = True
        _component = None
        return {
            "model_name": resolved_name,
            "in_sample_accuracy": float((preds == y).mean()),
            "purged_cv_accuracy": validation.purged_cv_accuracy,
            "purged_cv_n": validation.purged_cv_n,
            "prediction_std": validation.prediction_std,
            "is_stub": validation.is_stub,
            "accepted": accepted,
            "n_train": int(len(y)),
            "n_estimators": n_estimators,
            "label": label_kind,
            "n_features": int(X.shape[1]),
            "top_feature": validation.top_features[0][0] if validation.top_features else "",
            "kept_last_good": True,
        }

    with open(path, "wb") as f:
        pickle.dump(
            {
                "model": model,
                "columns": list(FORECAST_FEATURE_COLUMNS),
                "label": label_kind,
                "n_estimators": n_estimators,
                "accepted": accepted,
                "cv_method": selection.method,
                "nested_winner": selection.winner.name,
            },
            f,
        )
    write_cv_sidecar(
        sidecar,
        cv=float(validation.purged_cv_accuracy),
        n=int(validation.purged_cv_n),
        extra={
            "cpcv": float(validation.cpcv_accuracy),
            "cpcv_n": int(validation.cpcv_n),
            "nested_cpcv": float(selection.outer_accuracy),
            "nested_winner": selection.winner.name,
            "cv_method": selection.method,
            "label": label_kind,
        },
    )
    try:
        from app.services.forecast.calibration import load_ece
        from app.services.forecast.model_registry import get_alias, set_alias

        prev = get_alias("live")
        ece = load_ece()
        if prev and prev != resolved_name:
            set_alias("shadow", prev, ece=ece.get("ece"), cv=None)
        set_alias(
            "live",
            resolved_name,
            ece=ece.get("ece"),
            cv=float(validation.purged_cv_accuracy),
        )
    except Exception:
        pass

    _component = None

    return {
        "model_name": resolved_name,
        "in_sample_accuracy": float((preds == y).mean()),
        "purged_cv_accuracy": validation.purged_cv_accuracy,
        "purged_cv_n": validation.purged_cv_n,
        "prediction_std": validation.prediction_std,
        "is_stub": validation.is_stub,
        "accepted": accepted,
        "n_train": int(len(y)),
        "n_estimators": n_estimators,
        "label": label_kind,
        "n_features": int(X.shape[1]),
        "top_feature": validation.top_features[0][0] if validation.top_features else "",
        "kept_last_good": False,
        "cv_method": selection.method,
        "nested_cpcv_accuracy": selection.outer_accuracy,
        "nested_winner": selection.winner.name,
    }


_component: GradientBoostForecastComponent | None = None


def get_gradient_boost_component() -> GradientBoostForecastComponent:
    global _component
    if _component is None:
        _component = GradientBoostForecastComponent()
    return _component
