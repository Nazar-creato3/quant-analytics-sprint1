"""Exchange market-hours logic for Terminal Market Hours panel.

Schedules are approximate regular sessions (no holiday calendar feed wired yet —
holidays surface as weekday closed outside regular windows only; holiday
detection is explicitly deferred in data_coverage).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from app.services.terminal_platform.market.schemas import MarketHoursRow

SessionStatus = Literal["open", "closed", "pre", "post", "holiday"]


@dataclass(frozen=True)
class _ExchangeSpec:
    exchange: str
    name: str
    tz: str
    # Regular continuous session (single block) OR morning+afternoon.
    open_t: time
    close_t: time
    pre_start: Optional[time] = None
    post_end: Optional[time] = None
    # Optional lunch break (TSE / SSE style).
    lunch_start: Optional[time] = None
    lunch_end: Optional[time] = None
    regular_label: str = ""


_EXCHANGES: tuple[_ExchangeSpec, ...] = (
    _ExchangeSpec(
        "NYSE",
        "New York Stock Exchange",
        "America/New_York",
        time(9, 30),
        time(16, 0),
        pre_start=time(4, 0),
        post_end=time(20, 0),
        regular_label="09:30–16:00 ET",
    ),
    _ExchangeSpec(
        "NASDAQ",
        "NASDAQ",
        "America/New_York",
        time(9, 30),
        time(16, 0),
        pre_start=time(4, 0),
        post_end=time(20, 0),
        regular_label="09:30–16:00 ET",
    ),
    _ExchangeSpec(
        "LSE",
        "London Stock Exchange",
        "Europe/London",
        time(8, 0),
        time(16, 30),
        regular_label="08:00–16:30 London",
    ),
    _ExchangeSpec(
        "TSE",
        "Tokyo Stock Exchange",
        "Asia/Tokyo",
        time(9, 0),
        time(15, 0),
        lunch_start=time(11, 30),
        lunch_end=time(12, 30),
        regular_label="09:00–11:30 / 12:30–15:00 JST",
    ),
    _ExchangeSpec(
        "SSE",
        "Shanghai Stock Exchange",
        "Asia/Shanghai",
        time(9, 30),
        time(15, 0),
        lunch_start=time(11, 30),
        lunch_end=time(13, 0),
        regular_label="09:30–11:30 / 13:00–15:00 CST",
    ),
    _ExchangeSpec(
        "NSE",
        "National Stock Exchange of India",
        "Asia/Kolkata",
        time(9, 15),
        time(15, 30),
        regular_label="09:15–15:30 IST",
    ),
    _ExchangeSpec(
        "MOEX",
        "Moscow Exchange",
        "Europe/Moscow",
        time(10, 0),
        time(18, 40),
        regular_label="10:00–18:40 MSK",
    ),
)


def _in_window(t: time, start: time, end: time) -> bool:
    return start <= t < end


def _status_for(spec: _ExchangeSpec, local: datetime) -> SessionStatus:
    if local.weekday() >= 5:
        return "closed"
    t = local.time()
    if spec.lunch_start and spec.lunch_end and _in_window(t, spec.lunch_start, spec.lunch_end):
        return "closed"
    if _in_window(t, spec.open_t, spec.close_t):
        # During lunch already handled; morning/afternoon both covered by open→close
        # only when no lunch, OR when outside lunch.
        if spec.lunch_start and spec.lunch_end:
            if t < spec.lunch_start or t >= spec.lunch_end:
                return "open"
            return "closed"
        return "open"
    if spec.pre_start and _in_window(t, spec.pre_start, spec.open_t):
        return "pre"
    if spec.post_end and _in_window(t, spec.close_t, spec.post_end):
        return "post"
    return "closed"


def _combine(local_date: datetime, t: time, tz: ZoneInfo) -> datetime:
    return datetime(
        local_date.year,
        local_date.month,
        local_date.day,
        t.hour,
        t.minute,
        t.second,
        tzinfo=tz,
    )


def _next_weekday(d: datetime) -> datetime:
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def _next_event(spec: _ExchangeSpec, local: datetime, status: SessionStatus) -> tuple[str, str]:
    tz = ZoneInfo(spec.tz)
    t = local.time()

    def iso(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).isoformat()

    if status == "pre":
        evt = _combine(local, spec.open_t, tz)
        return "open", iso(evt)
    if status == "open":
        if spec.lunch_start and spec.lunch_end and t < spec.lunch_start:
            return "lunch", iso(_combine(local, spec.lunch_start, tz))
        if spec.lunch_end and spec.lunch_start and t >= spec.lunch_end:
            return "close", iso(_combine(local, spec.close_t, tz))
        return "close", iso(_combine(local, spec.close_t, tz))
    if status == "post":
        nxt = _next_weekday(local)
        open_at = _combine(nxt, spec.open_t, tz)
        return "open", iso(open_at)
    # closed
    if local.weekday() < 5 and t < spec.open_t:
        if spec.pre_start and t < spec.pre_start:
            return "pre_market", iso(_combine(local, spec.pre_start, tz))
        return "open", iso(_combine(local, spec.open_t, tz))
    if (
        local.weekday() < 5
        and spec.lunch_end
        and spec.lunch_start
        and spec.lunch_start <= t < spec.lunch_end
    ):
        return "open", iso(_combine(local, spec.lunch_end, tz))
    nxt = _next_weekday(local)
    target = spec.pre_start or spec.open_t
    label = "pre_market" if spec.pre_start else "open"
    return label, iso(_combine(nxt, target, tz))


def session_status_for_exchange(exchange: str, now: Optional[datetime] = None) -> SessionStatus:
    """Public helper for index/session tagging."""
    now_utc = now or datetime.now(timezone.utc)
    for spec in _EXCHANGES:
        if spec.exchange.upper() == exchange.upper():
            local = now_utc.astimezone(ZoneInfo(spec.tz))
            return _status_for(spec, local)
    return "closed"


def build_market_hours(now: Optional[datetime] = None) -> list[MarketHoursRow]:
    """Return session status for major venues."""
    now_utc = now or datetime.now(timezone.utc)
    rows: list[MarketHoursRow] = []
    for spec in _EXCHANGES:
        tz = ZoneInfo(spec.tz)
        local = now_utc.astimezone(tz)
        status = _status_for(spec, local)
        event, event_at = _next_event(spec, local, status)
        rows.append(
            MarketHoursRow(
                exchange=spec.exchange,
                name=spec.name,
                timezone=spec.tz,
                status=status,
                local_time=local.strftime("%Y-%m-%d %H:%M %Z"),
                next_event=event,
                next_event_at=event_at,
                regular_hours=spec.regular_label or None,
            )
        )
    return rows
