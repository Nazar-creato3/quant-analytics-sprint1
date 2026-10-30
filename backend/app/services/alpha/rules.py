"""Turtle system 1/2 (units, ½N pyramid, 2N stop) + Donchian breakout.

Faithful to the original rules, not a one-bar channel flag:
  S1 entry 20d, skip next S1 if the last S1 trade won (wait for S2).
  S2 entry 55d always.
  Add up to 4 units every +0.5N.
  Stop 2N from last fill.
  S1 exit 10d opposite channel; S2 exit 20d opposite channel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from app.services.quant_desk.vol_target import turtle_unit_usd


@dataclass(frozen=True, slots=True)
class RuleSignal:
    family: str
    direction: int
    lookback: int
    note: str = ""


@dataclass(frozen=True, slots=True)
class TurtlePosition:
    system: str  # s1 | s2 | flat
    direction: int
    units: int
    unit_usd: float
    notional_usd: float
    stop: float
    last_add: float
    n: float
    note: str

    @property
    def size_mult(self) -> float:
        return min(1.0, max(0.0, self.units / 4.0))


def _channel(highs: np.ndarray, lows: np.ndarray, lookback: int) -> tuple[float, float] | None:
    if highs.size < lookback + 2:
        return None
    prior_h = float(np.max(highs[-(lookback + 1) : -1]))
    prior_l = float(np.min(lows[-(lookback + 1) : -1]))
    return prior_h, prior_l


def donchian_breakout(
    closes: Sequence[float],
    *,
    highs: Sequence[float] | None = None,
    lows: Sequence[float] | None = None,
    lookback: int = 20,
) -> RuleSignal:
    c = np.asarray(closes, dtype=float)
    h = np.asarray(highs if highs is not None else c, dtype=float)
    l = np.asarray(lows if lows is not None else c, dtype=float)
    ch = _channel(h, l, lookback)
    if ch is None:
        return RuleSignal("donchian", 0, lookback, "short_history")
    last = float(c[-1])
    if last > ch[0]:
        return RuleSignal("donchian", 1, lookback, "breakout_high")
    if last < ch[1]:
        return RuleSignal("donchian", -1, lookback, "breakout_low")
    return RuleSignal("donchian", 0, lookback, "inside_channel")


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, window: int = 20) -> np.ndarray:
    n = len(closes)
    tr = np.zeros(n)
    for i in range(n):
        if i == 0:
            tr[i] = highs[0] - lows[0]
        else:
            tr[i] = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
    atr = np.full(n, np.nan)
    if n >= window:
        atr[window - 1] = float(np.mean(tr[:window]))
        for i in range(window, n):
            atr[i] = (atr[i - 1] * (window - 1) + tr[i]) / window
    return atr


def simulate_turtle(
    closes: Sequence[float],
    *,
    highs: Sequence[float] | None = None,
    lows: Sequence[float] | None = None,
    equity_usd: float = 100_000.0,
    risk_frac: float = 0.01,
) -> TurtlePosition:
    """Walk the full Turtle book on the series; return the *current* position."""
    c = np.asarray(closes, dtype=float)
    h = np.asarray(highs if highs is not None else c, dtype=float)
    l = np.asarray(lows if lows is not None else c, dtype=float)
    n_bars = int(c.size)
    if n_bars < 60:
        return TurtlePosition("flat", 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, "short_history")

    atr = _atr(h, l, c, 20)
    units = 0
    direction = 0
    system = "flat"
    last_add = 0.0
    stop = 0.0
    last_s1_won: bool | None = None
    skip_next_s1 = False
    entry_px = 0.0

    def _exit(i: int, reason: str) -> None:
        nonlocal units, direction, system, last_s1_won, skip_next_s1, last_add, stop, entry_px
        if units <= 0:
            return
        pnl = (float(c[i]) - entry_px) * direction
        if system == "s1":
            last_s1_won = pnl > 0
            skip_next_s1 = bool(last_s1_won)
        units = 0
        direction = 0
        system = "flat"
        last_add = stop = entry_px = 0.0

    def _enter(i: int, side: int, sys: str, n_val: float) -> None:
        nonlocal units, direction, system, last_add, stop, entry_px, skip_next_s1
        units = 1
        direction = side
        system = sys
        last_add = entry_px = float(c[i])
        stop = entry_px - side * 2.0 * n_val
        if sys == "s1":
            skip_next_s1 = False

    for i in range(55, n_bars):
        n_val = float(atr[i]) if not np.isnan(atr[i]) and atr[i] > 0 else 0.0
        if n_val <= 0:
            continue
        hi20 = float(np.max(h[i - 20 : i]))
        lo20 = float(np.min(l[i - 20 : i]))
        hi55 = float(np.max(h[i - 55 : i]))
        lo55 = float(np.min(l[i - 55 : i]))
        hi10 = float(np.max(h[i - 10 : i]))
        lo10 = float(np.min(l[i - 10 : i]))

        if units > 0:
            hit_stop = (direction > 0 and float(l[i]) <= stop) or (
                direction < 0 and float(h[i]) >= stop
            )
            if system == "s1":
                ch_exit = (direction > 0 and float(l[i]) <= lo10) or (
                    direction < 0 and float(h[i]) >= hi10
                )
            else:
                ch_exit = (direction > 0 and float(l[i]) <= lo20) or (
                    direction < 0 and float(h[i]) >= hi20
                )
            if hit_stop or ch_exit:
                _exit(i, "stop" if hit_stop else "channel")
                continue
            add_level = last_add + direction * 0.5 * n_val
            if units < 4 and (
                (direction > 0 and float(c[i]) >= add_level)
                or (direction < 0 and float(c[i]) <= add_level)
            ):
                units += 1
                last_add = float(c[i])
                stop = last_add - direction * 2.0 * n_val
            continue

        # Flat: entries (S2 always, S1 unless last S1 won).
        if float(c[i]) > hi20 and not skip_next_s1:
            _enter(i, 1, "s1", n_val)
        elif float(c[i]) < lo20 and not skip_next_s1:
            _enter(i, -1, "s1", n_val)
        elif float(c[i]) > hi55:
            _enter(i, 1, "s2", n_val)
        elif float(c[i]) < lo55:
            _enter(i, -1, "s2", n_val)

    n_now = float(atr[-1]) if not np.isnan(atr[-1]) else 0.0
    px = float(c[-1])
    unit = turtle_unit_usd(equity_usd=equity_usd, price=px, atr=max(n_now, 1e-9), risk_frac=risk_frac)
    return TurtlePosition(
        system=system,
        direction=direction,
        units=units,
        unit_usd=round(unit, 2),
        notional_usd=round(unit * units, 2),
        stop=float(stop),
        last_add=float(last_add),
        n=n_now,
        note=f"{system}:{units}u",
    )


def turtle_breakout(
    closes: Sequence[float],
    *,
    highs: Sequence[float] | None = None,
    lows: Sequence[float] | None = None,
    lookback: int = 55,
) -> RuleSignal:
    pos = simulate_turtle(closes, highs=highs, lows=lows)
    return RuleSignal("turtle", pos.direction, lookback, pos.note)


def primary_side(
    closes: Sequence[float],
    *,
    highs: Sequence[float] | None = None,
    lows: Sequence[float] | None = None,
    volumes: Sequence[float] | None = None,
) -> list[int]:
    """Bar-wise S1 (Donchian-20) side used as the meta-label primary bet."""
    del volumes
    c = np.asarray(closes, dtype=float)
    h = np.asarray(highs if highs is not None else c, dtype=float)
    l = np.asarray(lows if lows is not None else c, dtype=float)
    n = int(c.size)
    lookback = 20
    out = [0] * n
    for i in range(lookback + 1, n):
        prior_h = float(np.max(h[i - lookback : i]))
        prior_l = float(np.min(l[i - lookback : i]))
        px = float(c[i])
        if px > prior_h:
            out[i] = 1
        elif px < prior_l:
            out[i] = -1
    return out
