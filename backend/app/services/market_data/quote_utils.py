"""Shared helpers for normalizing provider quote payloads."""
from __future__ import annotations

from typing import Any


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _bar_field(bar: Any, key: str) -> float | None:
    if isinstance(bar, dict):
        return _to_float(bar.get(key))
    return _to_float(getattr(bar, key, None))


def enrich_quote_fields(quote: dict[str, Any], bars: list[Any] | None = None) -> dict[str, Any]:
    """Fill missing bid/ask/high/low/volume from alternate keys and latest daily bar."""
    out = dict(quote)

    for src, dst in (
        ("day_high", "high"),
        ("dayHigh", "high"),
        ("high_24h", "high"),
        ("regularMarketDayHigh", "high"),
        ("day_low", "low"),
        ("dayLow", "low"),
        ("low_24h", "low"),
        ("regularMarketDayLow", "low"),
        ("volume_24h", "volume"),
        ("regularMarketVolume", "volume"),
        ("change_percent", "change_pct"),
        ("changePercent", "change_pct"),
        ("percent_change", "change_pct"),
    ):
        if out.get(dst) is None and out.get(src) is not None:
            parsed = _to_float(out.get(src)) if dst != "change_pct" else out.get(src)
            if parsed is not None:
                out[dst] = parsed

    if bars:
        last = bars[-1]
        if out.get("high") is None:
            out["high"] = _bar_field(last, "high")
        if out.get("low") is None:
            out["low"] = _bar_field(last, "low")
        if out.get("volume") is None:
            out["volume"] = _bar_field(last, "volume")
        if out.get("open") is None:
            out["open"] = _bar_field(last, "open")

    price = extract_quote_price(out)
    if price is not None:
        out["price"] = price

    bid = _to_float(out.get("bid"))
    ask = _to_float(out.get("ask"))
    if bid is not None:
        out["bid"] = bid
    if ask is not None:
        out["ask"] = ask

    return out


def extract_quote_price(quote: dict[str, Any]) -> float | None:
    """Return a usable last/mid price from heterogeneous quote dicts."""
    for key in ("price", "last", "close"):
        raw = quote.get(key)
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value

    bid = quote.get("bid")
    ask = quote.get("ask")
    try:
        bid_f = float(bid) if bid is not None else None
        ask_f = float(ask) if ask is not None else None
    except (TypeError, ValueError):
        bid_f = ask_f = None

    if bid_f and bid_f > 0 and ask_f and ask_f > 0:
        return (bid_f + ask_f) / 2
    if bid_f and bid_f > 0:
        return bid_f
    if ask_f and ask_f > 0:
        return ask_f
    return None
