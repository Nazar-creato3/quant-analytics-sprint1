"""SHAP diagnostics for forecast LightGBM on held-out validation data."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from app.core.logging import get_logger
from app.services.forecast.forecast_features import FORECAST_FEATURE_COLUMNS, build_feature_matrix
from app.services.forecast.triple_barrier import TripleBarrierConfig, triple_barrier_labels
from app.services.quant_math import historical_volatility
from app.services.regime.features import prices_to_returns

logger = get_logger(__name__)

HIGH_VOL_PERCENTILE = 0.70
EARNINGS_PROX_THRESHOLD = 0.5


@dataclass
class ShapFeatureImportance:
    feature: str
    mean_abs_shap: float


@dataclass
class ShapRegimeSlice:
    regime: str
    n: int
    top_features: list[ShapFeatureImportance] = field(default_factory=list)


@dataclass
class ShapDiagnosticReport:
    symbol: str
    n_validation: int
    global_top_features: list[ShapFeatureImportance]
    high_volatility: ShapRegimeSlice
    low_volatility: ShapRegimeSlice
    earnings_window: ShapRegimeSlice
    non_earnings: ShapRegimeSlice
    shap_available: bool
    data_gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        def _slice(s: ShapRegimeSlice) -> dict[str, Any]:
            return {
                "regime": s.regime,
                "n": s.n,
                "top_features": [
                    {"feature": f.feature, "mean_abs_shap": f.mean_abs_shap} for f in s.top_features
                ],
            }

        return {
            "symbol": self.symbol,
            "n_validation": self.n_validation,
            "shap_available": self.shap_available,
            "data_gaps": self.data_gaps,
            "global_top_features": [
                {"feature": f.feature, "mean_abs_shap": f.mean_abs_shap}
                for f in self.global_top_features
            ],
            "high_volatility": _slice(self.high_volatility),
            "low_volatility": _slice(self.low_volatility),
            "earnings_window": _slice(self.earnings_window),
            "non_earnings": _slice(self.non_earnings),
        }


def _volatility_regime(prices: Sequence[float], idx: int, window: int = 20) -> str:
    if idx < window:
        return "low_volatility"
    returns = prices_to_returns(list(prices[: idx + 1]))
    vol = historical_volatility(returns[-window:])
    series = [
        historical_volatility(prices_to_returns(list(prices[max(0, i - window) : i + 1])))
        for i in range(window, len(prices))
    ]
    if not series:
        return "low_volatility"
    threshold = float(np.quantile(series, HIGH_VOL_PERCENTILE))
    return "high_volatility" if vol >= threshold else "low_volatility"


def _earnings_regime(earnings_proximity: float) -> str:
    return "earnings_window" if earnings_proximity >= EARNINGS_PROX_THRESHOLD else "non_earnings"


def _rank_features(shap_matrix: np.ndarray, top_n: int = 8) -> list[ShapFeatureImportance]:
    if shap_matrix.size == 0:
        return []
    mean_abs = np.mean(np.abs(shap_matrix), axis=0)
    pairs = sorted(
        zip(FORECAST_FEATURE_COLUMNS, mean_abs.tolist()),
        key=lambda p: p[1],
        reverse=True,
    )
    return [
        ShapFeatureImportance(feature=name, mean_abs_shap=round(float(val), 6))
        for name, val in pairs[:top_n]
    ]


def run_forecast_shap_diagnostics(
    closes: Sequence[float],
    *,
    symbol: str = "BENCHMARK",
    min_history: int = 30,
    validation_fraction: float = 0.2,
    enrichments: Sequence[dict[str, float]] | None = None,
    earnings_proximities: Sequence[float] | None = None,
) -> ShapDiagnosticReport:
    """Train/eval LightGBM and compute TreeSHAP on held-out tail."""
    gaps: list[str] = []
    labels = triple_barrier_labels(
        closes,
        config=TripleBarrierConfig(max_holding_days=10),
    )
    df = build_feature_matrix(closes, enrichments=enrichments, min_history=min_history)
    if df.empty or len(df) < 80:
        return ShapDiagnosticReport(
            symbol=symbol,
            n_validation=0,
            global_top_features=[],
            high_volatility=ShapRegimeSlice("high_volatility", 0),
            low_volatility=ShapRegimeSlice("low_volatility", 0),
            earnings_window=ShapRegimeSlice("earnings_window", 0),
            non_earnings=ShapRegimeSlice("non_earnings", 0),
            shap_available=False,
            data_gaps=["insufficient_samples"],
        )

    y_all = np.array(labels[min_history : min_history + len(df)])
    mask = y_all != 0
    X = df.values[mask]
    y = y_all[mask]
    if len(y) < 60:
        return ShapDiagnosticReport(
            symbol=symbol,
            n_validation=0,
            global_top_features=[],
            high_volatility=ShapRegimeSlice("high_volatility", 0),
            low_volatility=ShapRegimeSlice("low_volatility", 0),
            earnings_window=ShapRegimeSlice("earnings_window", 0),
            non_earnings=ShapRegimeSlice("non_earnings", 0),
            shap_available=False,
            data_gaps=["insufficient_labeled_samples"],
        )

    split = int(len(y) * (1.0 - validation_fraction))
    X_train, X_val = X[:split], X[split:]
    y_train, y_val = y[:split], y[split:]
    val_indices = np.where(mask)[0][split:]
    if len(y_val) < 10:
        return ShapDiagnosticReport(
            symbol=symbol,
            n_validation=len(y_val),
            global_top_features=[],
            high_volatility=ShapRegimeSlice("high_volatility", 0),
            low_volatility=ShapRegimeSlice("low_volatility", 0),
            earnings_window=ShapRegimeSlice("earnings_window", 0),
            non_earnings=ShapRegimeSlice("non_earnings", 0),
            shap_available=False,
            data_gaps=["validation_split_too_small"],
        )

    try:
        import lightgbm as lgb
    except ImportError:
        gaps.append("lightgbm_unavailable")
        return ShapDiagnosticReport(
            symbol=symbol,
            n_validation=len(y_val),
            global_top_features=[],
            high_volatility=ShapRegimeSlice("high_volatility", 0),
            low_volatility=ShapRegimeSlice("low_volatility", 0),
            earnings_window=ShapRegimeSlice("earnings_window", 0),
            non_earnings=ShapRegimeSlice("non_earnings", 0),
            shap_available=False,
            data_gaps=gaps,
        )

    model = lgb.LGBMClassifier(
        n_estimators=120,
        learning_rate=0.05,
        max_depth=4,
        num_leaves=16,
        min_child_samples=10,
        class_weight="balanced",
        random_state=42,
        verbose=-1,
    )
    model.fit(X_train, y_train)

    try:
        import shap
    except ImportError:
        gaps.append("shap_unavailable")
        return ShapDiagnosticReport(
            symbol=symbol,
            n_validation=len(y_val),
            global_top_features=[],
            high_volatility=ShapRegimeSlice("high_volatility", 0),
            low_volatility=ShapRegimeSlice("low_volatility", 0),
            earnings_window=ShapRegimeSlice("earnings_window", 0),
            non_earnings=ShapRegimeSlice("non_earnings", 0),
            shap_available=False,
            data_gaps=gaps,
        )

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_val)
    if isinstance(shap_values, list):
        shap_matrix = np.array(shap_values[1] if len(shap_values) > 1 else shap_values[0])
    else:
        shap_matrix = np.array(shap_values)

    global_top = _rank_features(shap_matrix)

    vol_buckets: dict[str, list[np.ndarray]] = {
        "high_volatility": [],
        "low_volatility": [],
    }
    earn_buckets: dict[str, list[np.ndarray]] = {
        "earnings_window": [],
        "non_earnings": [],
    }
    for row_idx, orig_idx in enumerate(val_indices):
        price_idx = min_history + int(orig_idx)
        vol_key = _volatility_regime(closes, price_idx)
        vol_buckets[vol_key].append(shap_matrix[row_idx])
        earn_prox = 0.0
        if earnings_proximities and price_idx < len(earnings_proximities):
            earn_prox = float(earnings_proximities[price_idx])
        elif "earnings_proximity" in df.columns:
            earn_prox = float(df.iloc[int(orig_idx)]["earnings_proximity"])
        earn_key = _earnings_regime(earn_prox)
        earn_buckets[earn_key].append(shap_matrix[row_idx])

    def _slice(name: str, rows: list[np.ndarray]) -> ShapRegimeSlice:
        if not rows:
            return ShapRegimeSlice(name, 0)
        mat = np.vstack(rows)
        return ShapRegimeSlice(name, len(rows), _rank_features(mat))

    return ShapDiagnosticReport(
        symbol=symbol,
        n_validation=len(y_val),
        global_top_features=global_top,
        high_volatility=_slice("high_volatility", vol_buckets["high_volatility"]),
        low_volatility=_slice("low_volatility", vol_buckets["low_volatility"]),
        earnings_window=_slice("earnings_window", earn_buckets["earnings_window"]),
        non_earnings=_slice("non_earnings", earn_buckets["non_earnings"]),
        shap_available=True,
        data_gaps=gaps,
    )
