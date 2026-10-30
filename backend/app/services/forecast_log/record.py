"""Record a forecast emission into the append-only log (Prompt 11A)."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.services.forecast_log.store import ForecastLogRow, get_store
from app.services.qa.feature_flags import is_enabled

DEFAULT_BASKET = (
    "SBER,GAZP,LKOH,GMKN,ROSN,IMOEX,AAPL,MSFT,SPY,QQQ,BTC-USD"
)


def feature_hash(parts: list[str]) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def direction_from_sign(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        low = value.lower()
        if low in {"buy", "long", "up", "bull"}:
            return 1
        if low in {"sell", "short", "down", "bear"}:
            return -1
        if low in {"wait", "hold", "flat", "neutral"}:
            return 0
    try:
        num = float(value)
    except (TypeError, ValueError):
        return 0
    if num > 0:
        return 1
    if num < 0:
        return -1
    return 0


def record_emission(
    *,
    ticker: str,
    instrument_id: str | int,
    horizon_days: int,
    direction: int,
    probability: Decimal | float | str,
    section: str,
    model_id: str,
    model_version: str,
    feature_parts: list[str] | None = None,
    interval_low: str | None = None,
    interval_high: str | None = None,
    issued_price: str | None = None,
    issued_price_source: str = "unknown",
    issued_at: datetime | None = None,
) -> ForecastLogRow | None:
    if not is_enabled("qa_forecast_log"):
        return None
    store = get_store()
    return store.append(
        {
            "issued_at": issued_at or datetime.now(timezone.utc),
            "instrument_id": str(instrument_id),
            "ticker": ticker.strip().upper(),
            "horizon_days": int(horizon_days),
            "direction": int(direction),
            "probability": str(Decimal(str(probability))),
            "interval_low": interval_low,
            "interval_high": interval_high,
            "section": section,
            "model_id": model_id,
            "model_version": model_version,
            "feature_hash": feature_hash(feature_parts or [ticker, section, model_id]),
            "issued_price": issued_price,
            "issued_price_source": issued_price_source,
        }
    )


def emit_from_forecast_out(out: Any, *, section: str = "forecast") -> ForecastLogRow | None:
    """Best-effort extract from ForecastOut / dict. Never raises to callers."""
    try:
        symbol = getattr(out, "symbol", None) or out.get("symbol")
        instrument_id = getattr(out, "instrument_id", None)
        if instrument_id is None and isinstance(out, dict):
            instrument_id = out.get("instrument_id") or symbol
        ensemble = getattr(out, "ensemble_forecast", None)
        if ensemble is None and isinstance(out, dict):
            ensemble = out.get("ensemble_forecast")
        conformal = getattr(out, "conformal_intervals", None)
        if conformal is None and isinstance(out, dict):
            conformal = out.get("conformal_intervals")
        action = getattr(out, "action_recommendation", None)
        if action is None and isinstance(out, dict):
            action = out.get("action_recommendation")
        confidence = getattr(out, "confidence", None)
        if confidence is None and isinstance(out, dict):
            confidence = out.get("confidence") or out.get("calibrated_confidence") or "0.5"
        consensus = None
        if ensemble is not None:
            consensus = (
                ensemble.get("direction_consensus")
                if isinstance(ensemble, dict)
                else getattr(ensemble, "direction_consensus", None)
            )
        direction = direction_from_sign(consensus)
        if direction == 0:
            direction = direction_from_sign(action)
        horizon = 5
        low = high = None
        if conformal is not None:
            if isinstance(conformal, dict):
                horizon = int(conformal.get("horizon_days") or 5)
                low = str(conformal.get("lower_70") or "") or None
                high = str(conformal.get("upper_70") or "") or None
            else:
                horizon = int(getattr(conformal, "horizon_days", None) or 5)
                low = str(getattr(conformal, "lower_70", None) or "") or None
                high = str(getattr(conformal, "upper_70", None) or "") or None
        return record_emission(
            ticker=str(symbol),
            instrument_id=instrument_id or symbol,
            horizon_days=horizon,
            direction=direction,
            probability=confidence if confidence is not None else "0.5",
            section=section,
            model_id="hierarchy_ensemble",
            model_version="v1",
            interval_low=low,
            interval_high=high,
            issued_price_source="issued_spot_not_eod",
        )
    except Exception:
        return None


def emit_from_chat_payload(payload: dict[str, Any]) -> ForecastLogRow | None:
    try:
        return record_emission(
            ticker=str(payload.get("ticker") or ""),
            instrument_id=str(payload.get("ticker") or ""),
            horizon_days=5,
            direction=direction_from_sign(payload.get("expected_return_sign")),
            probability=payload.get("calibrated_confidence") or "0.5",
            section="ai_chat",
            model_id="hierarchy_point",
            model_version="v1",
            issued_price_source="issued_spot_not_eod",
        )
    except Exception:
        return None


def emit_from_market_payload(payload: dict[str, Any]) -> ForecastLogRow | None:
    try:
        regime = payload.get("dominant_regime") or payload.get("regime") or "market"
        conf = payload.get("confidence") or payload.get("calibrated_confidence") or "0.5"
        return record_emission(
            ticker="MARKET",
            instrument_id="MARKET",
            horizon_days=20,
            direction=0,
            probability=conf,
            section="market_analysis",
            model_id="market_forecast",
            model_version="v1",
            feature_parts=["MARKET", str(regime)],
            issued_price_source="none",
        )
    except Exception:
        return None
