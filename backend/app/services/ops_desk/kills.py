"""Kill switches: daily loss, drawdown, stale data, broker disconnect."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence


@dataclass(frozen=True, slots=True)
class Kill:
    name: str
    tripped: bool
    detail: str


def daily_loss_kill(day_pnl_frac: float, *, limit: float = -0.05) -> Kill:
    hit = float(day_pnl_frac) <= float(limit)
    return Kill("daily_loss", hit, f"day_pnl={day_pnl_frac:.4f} limit={limit:.4f}")


def drawdown_kill(dd_frac: float, *, limit: float = 0.10) -> Kill:
    hit = float(dd_frac) >= float(limit)
    return Kill("drawdown", hit, f"dd={dd_frac:.4f} limit={limit:.4f}")


def stale_data_kill(
    last_bar: datetime | None,
    *,
    now: datetime | None = None,
    max_age_hours: float = 36.0,
) -> Kill:
    clock = now or datetime.now(timezone.utc)
    if last_bar is None:
        return Kill("data_stale", True, "нет данных")
    ts = last_bar if last_bar.tzinfo else last_bar.replace(tzinfo=timezone.utc)
    age_h = (clock - ts).total_seconds() / 3600.0
    return Kill("data_stale", age_h > max_age_hours, f"age_h={age_h:.2f} max={max_age_hours}")


def broker_disconnect_kill(connected: bool | None) -> Kill:
    if connected is None:
        return Kill("broker_disconnect", True, "нет данных")
    return Kill("broker_disconnect", connected is False, "disconnected" if not connected else "connected")


def evaluate_kills(
    *,
    day_pnl_frac: float = 0.0,
    dd_frac: float = 0.0,
    last_bar: datetime | None = None,
    broker_connected: bool | None = None,
    daily_limit: float = -0.05,
    dd_limit: float = 0.10,
    stale_hours: float = 36.0,
    now: datetime | None = None,
) -> tuple[bool, list[Kill]]:
    kills = [
        daily_loss_kill(day_pnl_frac, limit=daily_limit),
        drawdown_kill(dd_frac, limit=dd_limit),
        stale_data_kill(last_bar, now=now, max_age_hours=stale_hours),
        broker_disconnect_kill(broker_connected),
    ]
    return any(k.tripped for k in kills), kills
