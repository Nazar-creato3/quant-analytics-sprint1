"""Fit one LightGBM (or stub) per 1d/5d/21d horizon on primary TB+meta labels."""
from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from app.services.alpha.horizons import ALPHA_HORIZONS, horizon_specs
from app.services.alpha.labels import primary_labels
from app.services.alpha.nested_cpcv import (
    Candidate,
    default_lgbm_candidates,
    nested_cpcv_select,
)


def _lgbm_fit_predict(Xtr, ytr, Xte, params: dict) -> np.ndarray:
    try:
        import lightgbm as lgb
    except Exception:
        # Majority-class stub keeps unit tests vendor-free.
        vals, counts = np.unique(ytr, return_counts=True)
        fill = int(vals[int(np.argmax(counts))]) if vals.size else 0
        return np.full(len(Xte), fill)
    clf = lgb.LGBMClassifier(
        n_estimators=int(params.get("n_estimators", 120)),
        learning_rate=0.05,
        max_depth=int(params.get("max_depth", 4)),
        num_leaves=int(params.get("num_leaves", 16)),
        min_child_samples=10,
        subsample=0.8,
        colsample_bytree=0.8,
        class_weight="balanced",
        random_state=42,
        verbose=-1,
    )
    clf.fit(Xtr, ytr)
    return np.asarray(clf.predict(Xte))


def train_horizon_stack(
    X: np.ndarray,
    closes: Sequence[float],
    *,
    highs: Sequence[float] | None = None,
    lows: Sequence[float] | None = None,
    volumes: Sequence[float] | None = None,
    horizons: Sequence[int] = ALPHA_HORIZONS,
    candidates: Sequence[Candidate] | None = None,
    min_history: int = 30,
) -> dict[str, Any]:
    """Train / select independently per horizon. Returns cards of nested CPCV winners."""
    cands = tuple(candidates or default_lgbm_candidates())
    reports: dict[str, Any] = {}
    for spec in horizon_specs(horizons):
        lab = primary_labels(
            closes, highs=highs, lows=lows, horizon=spec.days, volumes=volumes
        )
        y_full = np.array(lab.side)
        start = min_history
        y = y_full[start : start + len(X)]
        if len(y) != len(X):
            n = min(len(y), len(X))
            y = y[:n]
            Xh = X[:n]
        else:
            Xh = X
        mask = y != 0
        if int(mask.sum()) < 20:
            reports[spec.model_suffix] = {
                "horizon": spec.days,
                "skipped": True,
                "reason": "too_few_tb_labels",
                "n_side": lab.n_side,
                "label_recipe": lab.recipe,
            }
            continue
        sel = nested_cpcv_select(
            Xh[mask],
            y[mask],
            cands,
            _lgbm_fit_predict,
            label_horizon=spec.days,
        )
        reports[spec.model_suffix] = {
            "horizon": spec.days,
            "skipped": False,
            "winner": sel.winner.name,
            "params": sel.winner.params,
            "outer_accuracy": sel.outer_accuracy,
            "outer_n": sel.outer_n,
            "cv_method": sel.method,
            "label_recipe": lab.recipe,
            "n_take": lab.n_take,
            "inner_scores": list(sel.inner_scores),
        }
    return {"horizons": list(horizons), "reports": reports}
