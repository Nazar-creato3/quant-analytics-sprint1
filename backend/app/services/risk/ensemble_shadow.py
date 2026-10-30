"""Shadow-compare forecast ensemble vs DirectionClassifier. Does not change the live side."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _shadow_path() -> Path:
    raw = getattr(settings, "PIT_STORE_DIR", "") or ""
    base = Path(raw) if str(raw).strip() else Path(__file__).resolve().parents[3] / "data"
    folder = base / "ensemble_shadow"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "compare.jsonl"


def side_from_direction(direction: str) -> int:
    d = str(direction or "").lower()
    if d == "long":
        return 1
    if d == "short":
        return -1
    return 0


def side_from_ensemble(forecast: Any) -> int:
    if forecast is None:
        return 0
    try:
        return int(getattr(forecast, "direction_consensus", 0) or 0)
    except (TypeError, ValueError):
        return 0


def ensemble_confidence(forecast: Any) -> float | None:
    if forecast is None:
        return None
    total = int(getattr(forecast, "models_total", 0) or 0)
    agree = int(getattr(forecast, "models_agreeing", 0) or 0)
    if total <= 0:
        return None
    return max(0.0, min(1.0, agree / total))


def _jsonable_features(features: dict[str, Any] | None) -> dict[str, Any]:
    if not features:
        return {}
    keep = (
        "vwap_deviation",
        "vwap_deviation_rel",
        "vwap_source",
        "spread",
        "spread_zscore",
        "spread_median",
        "roll_reason",
        "roll_price_source",
        "kyle_lambda",
        "alpha003",
    )
    out: dict[str, Any] = {}
    for key in keep:
        if key not in features:
            continue
        val = features[key]
        if isinstance(val, float):
            out[key] = round(val, 8) if val == val else None
        else:
            out[key] = val
    return out


def compare_row(
    *,
    ticker: str,
    clf_direction: str,
    clf_confidence: float,
    forecast: Any,
    features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ens_side = side_from_ensemble(forecast)
    clf_side = side_from_direction(clf_direction)
    row: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker.upper(),
        "classifier_direction": clf_direction,
        "classifier_side": clf_side,
        "classifier_confidence": round(float(clf_confidence), 4),
        "ensemble_side": ens_side,
        "ensemble_confidence": ensemble_confidence(forecast),
        "disagree": ens_side != 0 and clf_side != 0 and ens_side != clf_side,
        "used_for_maneuver": False,
    }
    packed = _jsonable_features(features)
    if packed:
        row["features"] = packed
    return row


def persist_shadow(row: dict[str, Any]) -> None:
    try:
        with _shadow_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.debug("ensemble_shadow_persist_failed", error=str(exc)[:120])


def run_shadow(
    ticker: str,
    closes: Sequence[float],
    *,
    clf_direction: str,
    clf_confidence: float,
    features: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not bool(getattr(settings, "MANEUVER_ENSEMBLE_SHADOW", True)):
        return None
    import os

    if os.getenv("PYTEST_CURRENT_TEST") and not os.getenv("MANEUVER_SHADOW_FORCE"):
        return None
    if len(closes) < 30:
        return None
    try:
        from app.services.forecast.ensemble import get_ensemble_forecast_engine

        forecast = get_ensemble_forecast_engine().compute(list(closes), symbol=ticker)
    except Exception as exc:
        logger.info("ensemble_shadow_failed", ticker=ticker, error=str(exc)[:160])
        return {"ticker": ticker.upper(), "error": "нет данных", "used_for_maneuver": False}
    row = compare_row(
        ticker=ticker,
        clf_direction=clf_direction,
        clf_confidence=clf_confidence,
        forecast=forecast,
        features=features,
    )
    persist_shadow(row)
    logger.info(
        "ensemble_shadow",
        ticker=ticker,
        classifier=clf_direction,
        ensemble_side=row["ensemble_side"],
        disagree=row["disagree"],
    )
    return row


def maybe_override_from_ensemble(
    *,
    direction: str,
    confidence: float,
    forecast: Any,
) -> tuple[str, float]:
    """Live switch — only when MANEUVER_SIGNAL_SOURCE=ensemble."""
    source = str(getattr(settings, "MANEUVER_SIGNAL_SOURCE", "classifier") or "classifier").lower()
    if source != "ensemble" or forecast is None:
        return direction, confidence
    side = side_from_ensemble(forecast)
    if side > 0:
        return "long", float(ensemble_confidence(forecast) or confidence)
    if side < 0:
        return "short", float(ensemble_confidence(forecast) or confidence)
    return "neutral", confidence
