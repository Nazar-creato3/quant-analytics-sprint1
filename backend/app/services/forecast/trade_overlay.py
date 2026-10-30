"""Forecast overlay on maneuvers: never increases size, may skip or shrink.

p_beat and conformal are optional. Missing model → no change (honest no-op).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from app.core.logging import get_logger

logger = get_logger(__name__)


def _lgbm_artifact_exists(ticker: str) -> bool:
    try:
        from app.services.forecast.gradient_boost_component import model_name_for_symbol
        from app.services.ml.model import MODEL_DIR

        return any(
            (MODEL_DIR / f"{model_name_for_symbol(ticker, horizon=h)}.pkl").is_file()
            for h in (5, 21, 20, 1)
        )
    except Exception:
        return False


@dataclass(frozen=True, slots=True)
class ForecastOverlay:
    allow: bool
    size_mult: float
    p_beat_20: float | None
    p_calibrated: float | None
    conformal_method: str
    reason: str
    meta: dict[str, Any] = field(default_factory=dict)


def shrink_probability(p: float, *, observed_acc: float | None, n: int, n0: int = 20) -> float:
    """Pull p toward observed hit-rate when enough resolved snapshots exist."""
    raw = min(1.0, max(0.0, float(p)))
    if observed_acc is None or n < n0:
        return raw
    acc = min(1.0, max(0.0, float(observed_acc)))
    w = n / (n + n0)
    return (1.0 - w) * raw + w * acc


def size_mult_from_p(p_cal: float, *, direction: str) -> float:
    """Kelly clip vs the side. Always ≤ 1. Broken ECE → 0."""
    from app.services.forecast.calibration import kelly_mult, load_ece

    ece = load_ece()
    if float(ece.get("n") or 0) >= 40 and not ece.get("reliable", True):
        return 0.0
    p = min(1.0, max(0.0, float(p_cal)))
    side_p = p if direction == "long" else (1.0 - p)
    k = kelly_mult(side_p, payoff=1.0, cap=0.25)
    if k <= 0:
        return 0.0
    return max(0.35, min(1.0, k))


def conformal_blocks_direction(direction: str, interval: Any) -> bool:
    """Block only when the 70% interval is against the side and data is enough."""
    if interval is None or not getattr(interval, "sufficient_data", False):
        return False
    try:
        lo = float(interval.lower_70)
        hi = float(interval.upper_70)
    except (TypeError, ValueError, AttributeError):
        return False
    if direction == "long" and hi <= 0.0:
        return True
    if direction == "short" and lo >= 0.0:
        return True
    return False


def apply_forecast_overlay(
    *,
    ticker: str,
    direction: str,
    closes: Sequence[float],
    observed_acc: float | None = None,
    observed_n: int = 0,
    mesh_confidence: float = 0.0,
) -> ForecastOverlay:
    meta: dict[str, Any] = {"ticker": ticker.upper(), "direction": direction}
    if direction not in {"long", "short"}:
        return ForecastOverlay(True, 1.0, None, None, "skipped", "neutral", meta)

    interval = None
    method = "none"
    from app.services.forecast.bar_quality import bars_dq, last_bar_sane

    dq = bars_dq(closes)
    bars_ok = bool(dq.get("ok")) and last_bar_sane(closes)
    meta["bar_dq"] = dq
    meta["bar_sane"] = bars_ok

    if len(closes) >= 32 and bars_ok:
        try:
            from app.services.forecast.conformal import cheap_return_interval

            tail = [float(x) for x in closes[-80:]]
            point = (tail[-1] / tail[-6] - 1.0) if len(tail) >= 6 and tail[-6] > 0 else 0.0
            interval = cheap_return_interval(tail, point, horizon_days=20)
            method = interval.method
            meta["conformal"] = interval.to_dict()
        except Exception as exc:
            logger.debug("conformal overlay skipped", ticker=ticker, error=str(exc)[:120])

        if conformal_blocks_direction(direction, interval):
            meta["blocked"] = "conformal_against_side"
            # Cheap conformal without a trained beat-model is a shade, not a hard veto.
            # A hard skip here emptied the daily book whenever LightGBM artifacts were missing.
            if _lgbm_artifact_exists(ticker):
                return ForecastOverlay(False, 0.0, None, None, method, "conformal_against_side", meta)
            return ForecastOverlay(True, 0.55, None, None, method, "conformal_against_side_soft", meta)

    p_raw: float | None = None
    p_cal: float | None = None
    if bars_ok and len(closes) >= 40 and _lgbm_artifact_exists(ticker):
        try:
            from app.services.forecast.gradient_boost_component import get_gradient_boost_component

            gb = get_gradient_boost_component()
            pred5 = gb.predict(list(closes), symbol=ticker, horizon=5)
            pred21 = gb.predict(list(closes), symbol=ticker, horizon=21)
            pred = pred21 if pred21.available else pred5
            if pred.available:
                p_raw = float(pred.beat_probability)
                p_cal = shrink_probability(p_raw, observed_acc=observed_acc, n=observed_n)
                meta["p_beat_5"] = float(pred5.beat_probability) if pred5.available else None
                meta["p_beat_21"] = float(pred21.beat_probability) if pred21.available else None
                meta["p_beat_20"] = meta["p_beat_21"]
                meta["p_calibrated"] = p_cal
                meta["model_accepted"] = bool(pred.accepted)
        except Exception as exc:
            logger.debug("p_beat overlay skipped", ticker=ticker, error=str(exc)[:120])

    mult = 1.0
    if p_cal is not None:
        from app.services.forecast.meta_label import meta_label_take

        if not meta_label_take(
            direction=direction,
            p_calibrated=p_cal,
            mesh_confidence=mesh_confidence,
        ):
            meta["blocked"] = "meta_label_skip"
            return ForecastOverlay(False, 0.0, p_raw, p_cal, method, "meta_label_skip", meta)
        mult = size_mult_from_p(p_cal, direction=direction)
        meta["size_mult"] = mult
        if mult <= 0:
            meta["blocked"] = "kelly_or_ece"
            return ForecastOverlay(False, 0.0, p_raw, p_cal, method, "kelly_or_ece", meta)
    return ForecastOverlay(True, mult, p_raw, p_cal, method, "applied" if p_cal is not None else "conformal_only", meta)
