"""Pooled A+B LightGBM: many names × days, not one skinny series."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

from app.core.logging import get_logger
from app.services.forecast.cs_cache import ranks_from_returns, save_cs_features
from app.services.forecast.excess_labels import excess_direction_labels
from app.services.forecast.forecast_features import FORECAST_FEATURE_COLUMNS, build_forecast_feature_row
from app.services.forecast.gradient_boost_component import (
    _adaptive_estimators,
    validate_trained_lgbm,
)
from app.services.ml.model import MODEL_DIR

logger = get_logger(__name__)

PANEL_MODEL = "forecast_direction_lgbm_PANEL"
MIN_PANEL_NAMES = 4
MIN_HISTORY = 30


def panel_model_name(horizon: int) -> str:
    h = int(horizon)
    if h == 20:
        return PANEL_MODEL
    return f"{PANEL_MODEL}_h{h}"


def _series_at(seq: Sequence[float] | None, end: int) -> list[float] | None:
    if not seq:
        return None
    return list(seq[: end + 1])


def build_panel_xy(
    universe: Mapping[str, Mapping[str, Sequence[float]]],
    *,
    horizon: int = 20,
) -> tuple[np.ndarray, np.ndarray, dict[str, dict[str, float]]]:
    """Stack labeled rows. Calendar CS when dates align; else bars-from-end."""
    staged: list[tuple[str, int, int, dict[str, float], int, str | None]] = []
    latest_rets5: dict[str, float] = {}
    latest_rets21: dict[str, float] = {}

    for symbol, pack in universe.items():
        closes = list(pack.get("closes") or [])
        if len(closes) < MIN_HISTORY + horizon + 5:
            continue
        from app.services.alpha.labels import primary_labels
        from app.services.forecast.cost_model import round_trip_cost_return

        prim = primary_labels(
            closes,
            highs=pack.get("highs"),
            lows=pack.get("lows"),
            horizon=horizon,
            volumes=pack.get("volumes"),
        )
        labels = list(prim.side)
        if prim.n_side < 20 or len(set(x for x in labels if x != 0)) < 2:
            labels = excess_direction_labels(
                closes,
                pack.get("benchmark"),
                horizon=horizon,
                cost_return=round_trip_cost_return(symbol),
            )
        highs = pack.get("highs")
        lows = pack.get("lows")
        volumes = pack.get("volumes")
        bench = pack.get("benchmark")
        dates = list(pack.get("dates") or [])
        n = len(closes)
        from app.services.forecast.asof_store import extras_as_of

        for i in range(MIN_HISTORY, n - horizon):
            if labels[i] == 0:
                continue
            offset = n - 1 - i
            day = str(dates[i])[:10] if len(dates) == n else None
            pit = extras_as_of(symbol, day) if day else {}
            row = build_forecast_feature_row(
                closes[: i + 1],
                volumes=_series_at(volumes, i),
                highs=_series_at(highs, i),
                lows=_series_at(lows, i),
                benchmark=_series_at(bench, i),
                extras=pit,
                allow_snapshot_fundamentals=bool(pit),
            )
            staged.append((symbol.upper(), offset, i, row, int(labels[i]), day))
        last = build_forecast_feature_row(
            closes,
            volumes=volumes,
            highs=highs,
            lows=lows,
            benchmark=bench,
            extras={},
            allow_snapshot_fundamentals=False,
        )
        latest_rets5[symbol.upper()] = float(last.get("ret_5") or 0.0)
        latest_rets21[symbol.upper()] = float(last.get("ret_21") or 0.0)

    if len({s[0] for s in staged}) < MIN_PANEL_NAMES or len(staged) < 200:
        raise ValueError("panel too thin for pooled LightGBM")

    by_key: dict[str, list[int]] = {}
    for idx, (_s, off, _i, _r, _y, day) in enumerate(staged):
        key = f"d:{day}" if day else f"o:{off}"
        by_key.setdefault(key, []).append(idx)

    for _off, idxs in by_key.items():
        rets5 = {staged[j][0] + str(j): staged[j][3].get("ret_5", 0.0) for j in idxs}
        rets21 = {staged[j][0] + str(j): staged[j][3].get("ret_21", 0.0) for j in idxs}
        r5 = ranks_from_returns(rets5)
        r21 = ranks_from_returns(rets21)
        breadth = next(iter(r5.values()), {}).get("breadth", 0.0)
        from app.services.alpha.neutralization import neutralize_cs

        neu5 = neutralize_cs([staged[j][3].get("ret_5", 0.0) for j in idxs])
        neu21 = neutralize_cs([staged[j][3].get("ret_21", 0.0) for j in idxs])
        for k, j in enumerate(idxs):
            key = staged[j][0] + str(j)
            staged[j][3]["cs_ret5_rank"] = float(np.clip(0.5 + neu5.z[k] / 6.0, 0.0, 1.0))
            staged[j][3]["cs_ret21_rank"] = float(np.clip(0.5 + neu21.z[k] / 6.0, 0.0, 1.0))
            staged[j][3]["cs_breadth"] = float(breadth)
            staged[j][3]["cs_ret5_z"] = float(neu5.z[k])
            staged[j][3]["cs_ret21_z"] = float(neu21.z[k])

    X = np.array([[t[3].get(c, 0.0) for c in FORECAST_FEATURE_COLUMNS] for t in staged])
    y = np.array([t[4] for t in staged])

    r5 = ranks_from_returns(latest_rets5)
    r21 = ranks_from_returns(latest_rets21)
    cache: dict[str, dict[str, float]] = {}
    breadth = next(iter(r5.values()), {}).get("breadth", 0.0)
    for sym in latest_rets5:
        cache[sym] = {
            "cs_ret5_rank": float((r5.get(sym) or {}).get("rank") or 0.0),
            "cs_ret21_rank": float((r21.get(sym) or {}).get("rank") or 0.0),
            "cs_breadth": float(breadth),
        }
    cache["_market"] = {"cs_ret5_rank": 0.5, "cs_ret21_rank": 0.5, "cs_breadth": float(breadth)}
    return X, y, cache


def train_panel_lgbm(
    universe: Mapping[str, Mapping[str, Sequence[float]]],
    *,
    horizon: int = 20,
) -> dict[str, Any]:
    import pickle

    import lightgbm as lgb

    X, y, cache = build_panel_xy(universe, horizon=horizon)
    n_estimators = _adaptive_estimators(len(y), X.shape[1])
    model = lgb.LGBMClassifier(
        n_estimators=n_estimators,
        learning_rate=0.05,
        max_depth=6,
        num_leaves=31,
        min_child_samples=25,
        subsample=0.8,
        colsample_bytree=0.7,
        class_weight="balanced",
        random_state=42,
        verbose=-1,
    )
    model.fit(X, y)
    validation = validate_trained_lgbm(model, X, y, label_horizon=horizon)
    accepted = (not validation.is_stub) and (
        validation.purged_cv_n < 40 or validation.purged_cv_accuracy >= 0.52
    )
    name = panel_model_name(horizon)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with open(MODEL_DIR / f"{name}.pkl", "wb") as f:
        pickle.dump(
            {
                "model": model,
                "columns": list(FORECAST_FEATURE_COLUMNS),
                "label": f"panel_excess_{horizon}",
                "n_estimators": n_estimators,
                "accepted": accepted,
            },
            f,
        )
    if horizon == 20:
        save_cs_features(cache)
    import app.services.forecast.gradient_boost_component as gbc

    gbc._component = None
    logger.info(
        "panel LightGBM trained",
        horizon=horizon,
        n=int(len(y)),
        n_estimators=n_estimators,
        accepted=accepted,
        cv=validation.purged_cv_accuracy,
    )
    return {
        "model_name": name,
        "n_train": int(len(y)),
        "n_estimators": n_estimators,
        "n_features": int(X.shape[1]),
        "purged_cv_accuracy": validation.purged_cv_accuracy,
        "purged_cv_n": validation.purged_cv_n,
        "accepted": accepted,
        "is_stub": validation.is_stub,
        "names": len({k for k in universe}),
    }
