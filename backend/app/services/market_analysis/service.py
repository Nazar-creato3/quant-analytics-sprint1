"""Market overview numbers from unified services (Prompt 45)."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from app.services.explanations.service import render as render_explanation
from app.services.forecast_core.service import for_market
from app.services.forecast_log.store import get_store
from app.services.market_regime.service import snapshot as regime_snapshot
from app.services.risk_engine.fhs import fhs_bundle
from app.services.risk_engine.series import get_series, snapshot as series_snapshot

CALENDAR_KINDS = ("dividend_cutoff", "earnings", "cbr", "expiration")


def _corr(a: list[float], b: list[float]) -> float | None:
    n = min(len(a), len(b))
    if n < 5:
        return None
    xa, xb = a[-n:], b[-n:]
    ma = sum(xa) / n
    mb = sum(xb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(xa, xb))
    da = math.sqrt(sum((x - ma) ** 2 for x in xa))
    db = math.sqrt(sum((y - mb) ** 2 for y in xb))
    if da < 1e-18 or db < 1e-18:
        return None
    return num / (da * db)


def _metric(value: float | None, *, source: str, as_of: str | None) -> dict[str, Any]:
    if value is None or not math.isfinite(value):
        return {
            "value": None,
            "data_status": "нет данных",
            "source": source,
            "as_of": as_of,
        }
    return {"value": value, "data_status": "ok", "source": source, "as_of": as_of}


def breadth() -> dict[str, Any]:
    bag = series_snapshot()
    up = down = 0
    missing = 0
    for ticker, rets in bag.items():
        if not rets:
            missing += 1
            continue
        last = rets[-1]
        if last > 0:
            up += 1
        elif last < 0:
            down += 1
    n = up + down
    if n == 0:
        return {
            "advancers": None,
            "decliners": None,
            "data_status": "нет данных",
            "source": "risk_engine.series",
            "note": "нет знака последнего дня — не 0",
        }
    return {
        "advancers": up,
        "decliners": down,
        "unchanged": max(0, len(bag) - up - down - missing),
        "data_status": "ok",
        "source": "risk_engine.series",
    }


def event_calendar() -> dict[str, Any]:
    """No invented cutoffs. Empty slots until a licensed feed is tagged."""
    as_of = datetime.now(timezone.utc).date().isoformat()
    events = [
        {
            "kind": kind,
            "date": None,
            "source": None,
            "updated_at": None,
            "data_status": "нет данных",
        }
        for kind in CALENDAR_KINDS
    ]
    return {
        "events": events,
        "data_status": "нет данных",
        "as_of": as_of,
        "reason": "нет письма на календарь отсечек/экспираций; ЦБ — macro_registry без даты заседания",
        "source": "market_analysis.calendar",
    }


def overview() -> dict[str, Any]:
    regime = regime_snapshot()
    market = regime["market"]
    imoex = get_series("IMOEX")
    sber = get_series("SBER")
    corr = _corr(imoex, sber)
    risk = None
    if len(imoex) >= 20:
        bundle = fhs_bundle(imoex)
        risk = {
            "var_95": bundle["var_95"],
            "es_975": bundle["es_975"],
            "method": "FHS",
            "source": "risk_engine.fhs",
            "data_status": "ok",
        }
    else:
        risk = {
            "var_95": None,
            "es_975": None,
            "method": "FHS",
            "source": "risk_engine.fhs",
            "data_status": "нет данных",
        }
    vol = market.get("volatility")
    vol_s = f"{float(vol):.4f}" if isinstance(vol, (int, float)) and math.isfinite(float(vol)) else "0"
    label = str(market.get("label") or "insufficient")
    text = render_explanation("market_regime", {"label": label, "vol": vol_s})
    forecasts = []
    for ticker in ("IMOEX", "SPY"):
        try:
            forecasts.append(for_market(ticker, 1))
        except Exception:
            forecasts.append({"ticker": ticker, "data_status": "нет данных", "source": "forecast_core"})
    log_rows = get_store().rows()
    recent = [row.ticker for row in log_rows[-20:]]
    return {
        "indices": {
            "IMOEX": _metric(
                sum(imoex[-1:]) if imoex else None,
                source="risk_engine.series",
                as_of=str(market.get("as_of")),
            )
        },
        "regime": market,
        "breadth": breadth(),
        "correlations": [
            {
                "a": "IMOEX",
                "b": "SBER",
                **_metric(corr, source="risk_engine.series", as_of=str(market.get("as_of"))),
            }
        ],
        "rates": _metric(None, source="macro_registry", as_of=None),
        "fx": _metric(
            (get_series("USDRUB") or [None])[-1] if get_series("USDRUB") else None,
            source="risk_engine.series",
            as_of=str(market.get("as_of")),
        ),
        "calendar": event_calendar(),
        "risk": risk,
        "text": text,
        "forecasts": forecasts,
        "forecast_log_tickers": recent,
        "source": "market_analysis",
    }
