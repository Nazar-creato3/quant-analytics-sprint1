"""One forecast(instrument, horizon) for every surface (Prompt 11).

Components declare availability. Missing stacking/LOB is visible, not
silently replaced by another model. Numbers from code; LLM does not set them.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.services.catalog.resolve import resolve
from app.services.forecast_log.record import record_emission
from app.services.forecast_log.summary import internal_summary
from app.services.qa.feature_flags import is_enabled
from app.services.risk_engine.series import get_series

MIN_N_DISABLE = 30
MODEL_ID = "forecast_core.heuristic.v1"


@dataclass(frozen=True)
class Component:
    name: str
    available: bool
    reason: str


def _horizon_gate(horizon_days: int) -> tuple[bool, str]:
    summary = internal_summary()
    for row in summary.get("horizons") or []:
        if int(row["horizon_days"]) != horizon_days:
            continue
        n = int(row["n"])
        if n >= MIN_N_DISABLE and not row.get("beats_naive"):
            return False, "горизонт отключён: точность не выше наивной модели по журналу"
        return True, "горизонт активен"
    return True, "мало наблюдений в журнале — горизонт включён"


def _heuristic(returns: list[float]) -> tuple[int | None, float | None]:
    if not returns:
        return None, None
    window = returns[-5:]
    momentum = sum(window)
    direction = 1 if momentum > 0 else (-1 if momentum < 0 else 0)
    prob = 0.5 + 0.15 * math.tanh(momentum * 20)
    return direction, min(0.85, max(0.15, prob))


def forecast(ticker: str, horizon_days: int = 1, *, section: str = "forecast") -> dict[str, Any]:
    if not is_enabled("qa_forecast_core"):
        raise RuntimeError("qa_forecast_core off")
    hit = resolve(ticker)
    series = get_series(hit.symbol) or get_series(ticker)
    stacking = Component("stacking", False, "файл модели ансамбля отсутствует")
    lob = Component("lob", False, "нет стакана для LOB-модели")
    heuristic = Component(
        "heuristic",
        bool(series),
        "импульс по ряду total_return" if series else "нет ряда total_return",
    )
    direction, probability = _heuristic(series)
    enabled, gate_reason = _horizon_gate(horizon_days)
    if not series:
        return {
            "ticker": hit.symbol,
            "asset_id": hit.asset_id,
            "horizon_days": horizon_days,
            "direction": None,
            "probability": None,
            "calibrated_probability": None,
            "interval": None,
            "horizon_enabled": enabled,
            "horizon_reason": gate_reason,
            "trust": "нет данных",
            "components": [
                {"name": stacking.name, "available": False, "reason": stacking.reason},
                {"name": lob.name, "available": False, "reason": lob.reason},
                {"name": heuristic.name, "available": False, "reason": heuristic.reason},
            ],
            "active_model": None,
            "degraded": True,
            "degraded_note": "нет ряда — прогноз не строится",
            "section": section,
            "source": "forecast_core",
            "data_status": "нет данных",
            "status": "insufficient_data",
            "reason": "нет ряда total_return",
        }
    trust = "низкая"
    if enabled and probability is not None and abs(probability - 0.5) > 0.08:
        trust = "средняя"
    payload: dict[str, Any] = {
        "ticker": hit.symbol,
        "asset_id": hit.asset_id,
        "horizon_days": horizon_days,
        "direction": direction if enabled else 0,
        "probability": probability if enabled else None,
        "horizon_enabled": enabled,
        "horizon_reason": gate_reason,
        "trust": trust,
        "components": [
            {"name": stacking.name, "available": stacking.available, "reason": stacking.reason},
            {"name": lob.name, "available": lob.available, "reason": lob.reason},
            {"name": heuristic.name, "available": heuristic.available, "reason": heuristic.reason},
        ],
        "active_model": MODEL_ID if heuristic.available else None,
        "degraded": True,
        "degraded_note": "доступен только эвристический компонент; stacking и LOB не подменяют его",
        "section": section,
        "source": "forecast_core",
        "data_status": "ok" if enabled and probability is not None else "недостаточно данных",
        "status": "ok" if enabled and probability is not None else "insufficient_data",
    }
    try:
        from app.services.model_risk.service import status as model_status
        from app.services.model_risk.math import conformal_interval

        ms = model_status()
        payload["model_status"] = ms["validation"]["status"]
        if payload["probability"] is not None:
            payload["calibrated_probability"] = 0.5 + 0.5 * (float(payload["probability"]) - 0.5)
            lo, hi = conformal_interval(series, float(payload["direction"] or 0), 0.1)
            payload["interval"] = {"low": lo, "high": hi, "method": "residual-quantile"}
        else:
            payload["calibrated_probability"] = None
            payload["interval"] = None
        payload["user_reason"] = ms["user_reason"]
        from app.services.model_risk.service import shadow_challenger
        from app.services.model_risk.math import naive_persist

        last = series[-1]
        shadow_challenger(hit.symbol, int(payload["direction"] or 0), 1 if last > 0 else (-1 if last < 0 else 0))
        payload["challenger"] = naive_persist(series)[-1]
        from app.services.market_regime.service import classify

        payload["regime"] = classify(series, scope="instrument", ticker=hit.symbol)
    except Exception:
        payload["calibrated_probability"] = payload.get("probability")
    if payload.get("probability") is not None:
        try:
            record_emission(
                ticker=hit.symbol,
                instrument_id=hit.asset_id,
                horizon_days=horizon_days,
                direction=int(payload["direction"] or 0),
                probability=str(payload["probability"]),
                section=section,
                model_id=MODEL_ID,
                model_version="v1",
                issued_price_source="series",
            )
        except Exception:
            pass
    return payload


def for_ui(ticker: str, horizon_days: int = 1) -> dict[str, Any]:
    return forecast(ticker, horizon_days, section="forecast")


def for_chat(ticker: str, horizon_days: int = 1) -> dict[str, Any]:
    return forecast(ticker, horizon_days, section="chat")


def for_market(ticker: str, horizon_days: int = 1) -> dict[str, Any]:
    return forecast(ticker, horizon_days, section="market")


def public_accuracy() -> dict[str, Any]:
    raw = internal_summary()
    raw["public"] = True
    raw["methodology"] = (
        "Точность направления по журналу forecast_log против наивной модели 50%. "
        "Интервал — Вильсон 95%. Горизонт отключается при n≥30 и accuracy ≤ naive."
    )
    return raw
