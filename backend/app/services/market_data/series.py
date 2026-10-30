"""Three price series: raw, split-adjusted, total return (our actions, not vendor)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

Kind = Literal["raw", "split_adj", "total_return"]


@dataclass(frozen=True)
class Bar:
    session_date: date
    close: Decimal


@dataclass(frozen=True)
class Action:
    session_date: date
    kind: Literal["split", "dividend", "coupon"]
    factor: Decimal = Decimal("1")  # split 10:1 → 10
    cash: Decimal = Decimal("0")


@dataclass(frozen=True)
class OhlcBar:
    session_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Decimal("0")


def get_series(bars: list[Bar], actions: list[Action], kind: Kind) -> list[Bar]:
    ordered = sorted(bars, key=lambda item: item.session_date)
    if kind == "raw":
        return list(ordered)
    split_by_day = {a.session_date: a for a in actions if a.kind == "split"}
    cash_by_day = {a.session_date: a for a in actions if a.kind in {"dividend", "coupon"}}
    if kind == "split_adj":
        factor = Decimal("1")
        out: list[Bar] = []
        for bar in reversed(ordered):
            act = split_by_day.get(bar.session_date)
            if act:
                factor *= act.factor
            out.append(Bar(bar.session_date, (bar.close / factor)))
        return list(reversed(out))
    # total_return: reinvest cash on ex date into the same instrument
    shares = Decimal("1")
    out_tr: list[Bar] = []
    for bar in ordered:
        cash_act = cash_by_day.get(bar.session_date)
        if cash_act and bar.close > 0:
            shares += cash_act.cash / bar.close
        split_act = split_by_day.get(bar.session_date)
        if split_act:
            shares *= split_act.factor
        out_tr.append(Bar(bar.session_date, bar.close * shares))
    return out_tr


def adjust_ohlc(bars: list[OhlcBar], actions: list[Action], kind: Kind) -> list[OhlcBar]:
    """Scale OHLC by the close ratio from ``get_series`` (Prompt 04 + 42)."""
    # One factor per session: several intraday bars can share a date, so the
    # factor is the day's adjusted/raw last close, applied to each bar's own
    # prices (never overwrite every bar of the day with the same close).
    last_raw: dict = {}
    for b in bars:
        last_raw[b.session_date] = b.close
    closes = get_series([Bar(d, c) for d, c in last_raw.items()], actions, kind)
    adj_close = {item.session_date: item.close for item in closes}
    out: list[OhlcBar] = []
    for bar in bars:
        raw_last = last_raw[bar.session_date]
        if bar.close == 0 or raw_last == 0:
            out.append(bar)
            continue
        scale = adj_close[bar.session_date] / raw_last
        new_close = bar.close * scale
        out.append(
            OhlcBar(
                bar.session_date,
                bar.open * scale,
                bar.high * scale,
                bar.low * scale,
                new_close,
                bar.volume,
            )
        )
    return out
