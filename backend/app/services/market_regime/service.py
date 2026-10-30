"""One regime classifier for market and instrument (Prompt 12).

Labels: trend_up / trend_down / range / volatility / crisis.
Versioned parameters. History + regime.changed when the label flips.
"""
from __future__ import annotations

import math
from datetime import date
from threading import Lock
from typing import Any, Literal, Sequence

from app.services.event_bus.bus import publish_event
from app.services.qa.feature_flags import is_enabled
from app.services.qa.shadow_mode import record_diff
from app.services.risk_engine.series import get_series

CONFIG_VERSION = "market_regime.v1"
Scope = Literal["market", "instrument"]
VOL_CRISIS = 0.035
VOL_HIGH = 0.022
CRISIS_DRAWDOWN_10 = -0.08
RANGE_MOMENTUM_MULT = 0.6

_lock = Lock()
_history: list[dict[str, Any]] = []
_last: dict[str, str] = {}


def _reset() -> None:
    with _lock:
        _history.clear()
        _last.clear()


def classify(
    returns: list[float],
    *,
    scope: Scope,
    ticker: str,
    as_of: date | None = None,
) -> dict[str, Any]:
    if not is_enabled("qa_market_regime"):
        raise RuntimeError("qa_market_regime off")
    values = [float(x) for x in returns if math.isfinite(float(x))]
    label, explain, vol, mom = _label(values)
    day = (as_of or date.today()).isoformat()
    insufficient = label == "insufficient"
    payload = {
        "scope": scope,
        "ticker": ticker.upper(),
        "label": label,
        "explain": explain,
        "volatility": vol,
        "momentum_10": mom,
        "as_of": day,
        "config_version": CONFIG_VERSION,
        "source": "market_regime",
        "status": "insufficient_data" if insufficient else "ok",
        "data_status": "нет данных" if insufficient else "ok",
    }
    with _lock:
        prev = _last.get(f"{scope}:{ticker.upper()}")
        _last[f"{scope}:{ticker.upper()}"] = label
        _history.append(payload)
        flipped = prev is not None and prev != label and not insufficient
    if flipped:
        try:
            publish_event(
                "regime.changed",
                {"scope": scope, "ticker": ticker.upper(), "label": label, "prev": prev, "user_id": "system"},
            )
        except Exception:
            pass
    return payload


def classify_from_prices(
    prices: list[float],
    *,
    scope: Scope,
    ticker: str,
) -> dict[str, Any]:
    rets: list[float] = []
    for a, b in zip(prices, prices[1:]):
        if a and float(a) > 0:
            rets.append(float(b) / float(a) - 1.0)
    return classify(rets, scope=scope, ticker=ticker)


def label_from_closes(closes: Sequence[float], *, ticker: str) -> str:
    """Canonical market_regime label for an OHLC close column."""
    prices = [float(x) for x in closes if x == x]
    return str(classify_from_prices(prices, scope="instrument", ticker=ticker)["label"])


def classify_ticker(ticker: str, *, scope: Scope = "instrument") -> dict[str, Any]:
    series = get_series(ticker)
    if not series:
        return classify([], scope=scope, ticker=ticker)
    return classify(series, scope=scope, ticker=ticker)


def snapshot(*, ticker: str | None = None) -> dict[str, Any]:
    market = classify_ticker("IMOEX", scope="market")
    inst = classify_ticker(ticker, scope="instrument") if ticker else None
    return {"market": market, "instrument": inst, "history": list(_history[-20:])}


def to_composer_regime(label: str) -> str:
    return {
        "trend_up": "trend_up",
        "trend_down": "trend_down",
        "range": "range",
        "volatility": "high_vol",
        "crisis": "high_vol",
        "insufficient": "unknown",
    }.get(label, "unknown")


def shadow_old_label(old: str, new_label: str) -> None:
    mapped = {"bull": "trend_up", "bear": "trend_down", "sideways": "range", "volatile": "volatility"}.get(
        old, "unknown"
    )
    from pathlib import Path

    record_diff(
        "regime",
        {"old": old},
        mapped,
        new_label,
        path=Path(__file__).resolve().parents[3] / "data" / "regime_shadow" / "compare.jsonl",
    )


def _label(values: list[float]) -> tuple[str, str, float, float]:
    if len(values) < 8:
        return "insufficient", "нет данных", 0.0, 0.0
    window = values[-20:]
    vol = _stdev(window)
    mom = 1.0
    for r in values[-10:]:
        mom *= 1.0 + r
    mom -= 1.0
    if vol >= VOL_CRISIS and mom <= CRISIS_DRAWDOWN_10:
        return "crisis", f"резкое падение ({mom:.1%}) при высокой волатильности — кризисный режим", vol, mom
    if vol >= VOL_HIGH:
        return "volatility", f"дневная волатильность {vol:.1%} выше порога {VOL_HIGH:.1%}", vol, mom
    if abs(mom) < RANGE_MOMENTUM_MULT * vol * math.sqrt(10):
        return "range", "импульс мал относительно волатильности — боковик", vol, mom
    if mom > 0:
        return "trend_up", f"10-дневный импульс {mom:.1%} при умеренной волатильности — восходящий тренд", vol, mom
    return "trend_down", f"10-дневный импульс {mom:.1%} — нисходящий тренд", vol, mom


def _stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    mean = sum(xs) / len(xs)
    var = sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(max(var, 0.0))
