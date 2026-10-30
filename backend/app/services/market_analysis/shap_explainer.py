"""SHAP explainability for LightGBM direction model (spec Section 6.3)."""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.schemas.ticker_analysis import ShapFactorContribution

logger = get_logger(__name__)

_SHAP_GAP = "shap_values (SHAP library unavailable)"


def shap_data_gap() -> str:
    return _SHAP_GAP


def compute_shap_top_factors(
    features: dict[str, float],
    *,
    top_n: int = 5,
) -> tuple[list[ShapFactorContribution] | None, bool, list[str]]:
    """
    Compute TreeSHAP contributions when shap + a loaded LightGBM model exist.
    Returns (contributions, shap_available, data_gaps).
    """
    gaps: list[str] = []
    try:
        from app.core.config import settings

        if settings.PIPELINE_SKIP_SHAP:
            gaps.append("shap_values (disabled for pipeline worker stability)")
            return None, False, gaps
        import shap  # noqa: F401
    except Exception as exc:  # noqa: BLE001 — TypeError on numpy>=2.4 + old shap
        gaps.append(f"shap_values ({exc})")
        return None, False, gaps

    try:
        import numpy as np

        from app.services.ml.features import get_feature_columns
        from app.services.ml.model import get_classifier

        classifier = get_classifier()
        if classifier._model is None:
            gaps.append("shap_values (LightGBM model file not loaded — using rule fallback)")
            return None, False, gaps

        feature_cols = get_feature_columns()
        vector = np.array([[features.get(col, 0.0) for col in feature_cols]])
        explainer = shap.TreeExplainer(classifier._model)
        shap_values = explainer.shap_values(vector)
        if isinstance(shap_values, list):
            values = shap_values[1][0] if len(shap_values) > 1 else shap_values[0][0]
        else:
            values = shap_values[0]

        pairs = sorted(
            zip(feature_cols, values),
            key=lambda item: abs(float(item[1])),
            reverse=True,
        )[:top_n]
        contributions = [
            ShapFactorContribution(feature=name, contribution=round(float(val), 6))
            for name, val in pairs
        ]
        return contributions, True, gaps
    except Exception as exc:
        logger.debug("SHAP computation failed", error=str(exc))
        gaps.append(f"shap_values ({exc})")
        return None, False, gaps


def features_from_prices_volumes(prices: list[float], volumes: list[float]) -> dict[str, float]:
    """Minimal feature vector for SHAP when full feature frame unavailable."""
    import pandas as pd

    from app.services.ml.features import compute_features

    if not prices:
        return {}
    rows = []
    for idx, close in enumerate(prices):
        vol = volumes[idx] if idx < len(volumes) else 0.0
        rows.append({"close": close, "volume": vol, "open": close, "high": close, "low": close})
    df = pd.DataFrame(rows)
    df_feat = compute_features(df)
    if df_feat.empty:
        return {}
    feature_cols = [c for c in df_feat.columns if c not in {"close", "open", "high", "low", "volume"}]
    row = df_feat.iloc[-1]
    return {col: float(row[col]) if not pd.isna(row[col]) else 0.0 for col in feature_cols}
