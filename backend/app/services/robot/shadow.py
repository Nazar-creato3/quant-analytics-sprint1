"""RobotPlan shadow / event-driven backtest with research knobs.

Replays OHLC through LevelMonitor semantics + optional slippage / latency / partials.
"""
from __future__ import annotations

import random
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.services.robot.monitor import _kind_priority, _level_hit, _update_trail_level
from app.services.robot.risk import drawdown_pct


@dataclass
class ShadowFill:
    bar: int
    kind: str
    price: float
    qty: float
    side: str
    realized_pnl: float = 0.0
    level_id: str | None = None


@dataclass
class ShadowResult:
    bars: int
    side: str
    entry: float
    qty_initial: float
    fills: list[ShadowFill] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)
    total_return: float = 0.0
    max_drawdown: float = 0.0
    realized_pnl: float = 0.0
    exit_reason: str | None = None
    final_qty: float = 0.0
    final_avg: float | None = None
    avg_slippage: float = 0.0
    avg_latency_bars: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": "robot_shadow",
            "bars": self.bars,
            "side": self.side,
            "entry": self.entry,
            "qty_initial": self.qty_initial,
            "fills": [
                {
                    "bar": f.bar,
                    "kind": f.kind,
                    "price": f.price,
                    "qty": f.qty,
                    "side": f.side,
                    "realized_pnl": f.realized_pnl,
                    "level_id": f.level_id,
                }
                for f in self.fills
            ],
            "equity_end": self.equity[-1] if self.equity else 0.0,
            "equity_curve": self.equity,
            "total_return": self.total_return,
            "max_drawdown": self.max_drawdown,
            "realized_pnl": self.realized_pnl,
            "exit_reason": self.exit_reason,
            "final_qty": self.final_qty,
            "final_avg": self.final_avg,
            "n_fills": len(self.fills),
            "avg_slippage": self.avg_slippage,
            "avg_latency_bars": self.avg_latency_bars,
        }


def _pnl(side: str, entry: float, exit_px: float, qty: float) -> float:
    if side == "short":
        return (entry - exit_px) * qty
    return (exit_px - entry) * qty


def shadow_to_dict(result: ShadowResult) -> dict[str, Any]:
    return result.to_dict()


def run_robot_shadow(
    bars: Sequence[dict[str, Any]] | Sequence[tuple[float, float, float]],
    *,
    levels: list[dict[str, Any]],
    side: str = "long",
    qty: float = 1.0,
    fee_rate: float = 0.0,
    kill_switch_pct: float | None = 5.0,
    slippage_pct: float = 0.0,
    latency_bars: int = 0,
    partial_fill_min: float = 1.0,
    seed: int | None = 42,
) -> ShadowResult:
    """Simulate RobotPlan over OHLC with optional research friction."""
    rng = random.Random(seed)
    side_n = "short" if str(side).lower() in {"short", "sell"} else "long"
    lvls = deepcopy(levels)
    entry_lv = next((lv for lv in lvls if lv.get("kind") == "entry"), None)
    entry = float(entry_lv["price"]) if entry_lv and entry_lv.get("price") else None
    if entry is None or entry <= 0:
        raise ValueError("levels must include entry with price")

    slip = max(float(slippage_pct), 0.0)
    latency = max(int(latency_bars), 0)
    pmin = min(max(float(partial_fill_min), 0.05), 1.0)

    def apply_slip(px: float, *, buy: bool) -> float:
        if slip <= 0:
            return px
        return px * (1.0 + slip) if buy else px * (1.0 - slip)

    def apply_partial(q: float) -> float:
        if pmin >= 0.999:
            return q
        return q * rng.uniform(pmin, 1.0)

    qty_open = float(qty)
    qty_initial = qty_open
    avg = entry
    cash_pnl = 0.0
    fills: list[ShadowFill] = []
    equity: list[float] = []
    peak_eq = qty_open * entry
    exit_reason: str | None = None
    fee = max(float(fee_rate), 0.0)
    slip_samples: list[float] = []
    latency_samples: list[int] = []
    # deferred: ready_bar, kind, price, qty, level, buy
    pending: list[dict[str, Any]] = []

    fills.append(
        ShadowFill(
            bar=0,
            kind="entry",
            price=entry,
            qty=qty_open,
            side="sell" if side_n == "short" else "buy",
            level_id=str(entry_lv.get("id")) if entry_lv else "entry",
        )
    )
    if entry_lv is not None:
        entry_lv["status"] = "filled"

    parsed: list[tuple[float, float, float]] = []
    for b in bars:
        if isinstance(b, dict):
            parsed.append((float(b["high"]), float(b["low"]), float(b["close"])))
        else:
            parsed.append((float(b[0]), float(b[1]), float(b[2])))

    def mark_eq(px: float) -> float:
        if qty_open <= 1e-12:
            return cash_pnl
        if side_n == "short":
            return cash_pnl + qty_open * (2 * avg - px)
        return cash_pnl + qty_open * px

    def execute(
        *,
        bar_i: int,
        kind: str,
        raw_px: float,
        fill_qty: float,
        lv: dict[str, Any],
        buy: bool,
    ) -> None:
        nonlocal qty_open, avg, cash_pnl, exit_reason
        px = apply_slip(raw_px, buy=buy)
        if raw_px > 0:
            slip_samples.append(abs(px - raw_px) / raw_px)
        take = apply_partial(fill_qty)
        if kind == "add":
            take = apply_partial(fill_qty)
            notional = avg * qty_open + px * take
            qty_open += take
            avg = notional / qty_open if qty_open > 0 else avg
            fee_cost = fee * px * take
            cash_pnl -= fee_cost
            fills.append(
                ShadowFill(
                    bar=bar_i, kind="add", price=px, qty=take,
                    side="sell" if side_n == "short" else "buy",
                    realized_pnl=-fee_cost, level_id=str(lv.get("id")),
                )
            )
            lv["status"] = "filled"
            return
        take = min(take, qty_open)
        if take <= 0:
            return
        pnl = _pnl(side_n, avg, px, take) - fee * px * take
        cash_pnl += pnl
        fills.append(
            ShadowFill(
                bar=bar_i, kind=kind, price=px, qty=take,
                side="buy" if side_n == "short" else "sell",
                realized_pnl=pnl, level_id=str(lv.get("id")),
            )
        )
        lv["status"] = "filled"
        qty_open = max(0.0, qty_open - take)
        if qty_open <= 1e-12:
            if kind == "sl":
                exit_reason = "stop"
            elif kind.startswith("tp"):
                exit_reason = "take_profit"
            else:
                exit_reason = kind

    def schedule_or_run(
        *,
        bar_i: int,
        kind: str,
        px: float,
        fill_qty: float,
        lv: dict[str, Any],
        buy: bool,
    ) -> None:
        if latency > 0:
            pending.append(
                {
                    "ready_bar": bar_i + latency,
                    "kind": kind,
                    "price": px,
                    "qty": fill_qty,
                    "level": lv,
                    "buy": buy,
                    "delay": latency,
                }
            )
            lv["status"] = "triggered"
            return
        execute(bar_i=bar_i, kind=kind, raw_px=px, fill_qty=fill_qty, lv=lv, buy=buy)

    for i, (high, low, close) in enumerate(parsed):
        if qty_open <= 1e-12 and not pending:
            equity.append(cash_pnl)
            break

        still: list[dict[str, Any]] = []
        for item in pending:
            if int(item["ready_bar"]) > i:
                still.append(item)
                continue
            latency_samples.append(int(item["delay"]))
            execute(
                bar_i=i,
                kind=str(item["kind"]),
                raw_px=float(item["price"]),
                fill_qty=float(item["qty"]),
                lv=item["level"],
                buy=bool(item["buy"]),
            )
        pending = still

        if qty_open <= 1e-12:
            equity.append(cash_pnl)
            continue

        eq = mark_eq(close)
        peak_eq = max(peak_eq, eq)
        if kill_switch_pct and drawdown_pct(peak=peak_eq, equity=eq) >= float(kill_switch_pct):
            execute(
                bar_i=i, kind="kill_switch", raw_px=close, fill_qty=qty_open,
                lv={"id": "kill"}, buy=(side_n == "short"),
            )
            exit_reason = "kill_switch"
            equity.append(cash_pnl)
            break

        closed_now = False
        for lv in lvls:
            if str(lv.get("kind")) != "trail":
                continue
            hit = _update_trail_level(lv, high=high, low=low, close=close, side_book=side_n)
            if hit and str(lv.get("status")) == "armed" and qty_open > 0:
                schedule_or_run(
                    bar_i=i, kind="trail", px=float(lv.get("price") or close),
                    fill_qty=qty_open, lv=lv, buy=(side_n == "short"),
                )
                if qty_open <= 1e-12:
                    closed_now = True

        if not closed_now and qty_open > 1e-12:
            ordered = sorted(
                enumerate(lvls),
                key=lambda pair: (_kind_priority(str(pair[1].get("kind") or "")), pair[0]),
            )
            for _idx, lv in ordered:
                if qty_open <= 1e-12:
                    break
                kind = str(lv.get("kind") or "")
                if kind in {"trail", "entry"}:
                    continue
                if str(lv.get("status")) not in {"watching", "pending", "armed"}:
                    continue
                if not _level_hit(lv, high=high, low=low, side_book=side_n):
                    continue
                px = float(lv.get("price") or close)
                if kind == "sl":
                    schedule_or_run(
                        bar_i=i, kind="sl", px=px, fill_qty=qty_open, lv=lv,
                        buy=(side_n == "short"),
                    )
                elif kind == "tp":
                    size_pct = float(lv.get("size_pct") or 100.0)
                    take = qty_open if size_pct >= 99.5 else qty_open * (size_pct / 100.0)
                    schedule_or_run(
                        bar_i=i,
                        kind="tp_partial" if size_pct < 99.5 else "tp",
                        px=px,
                        fill_qty=take,
                        lv=lv,
                        buy=(side_n == "short"),
                    )
                    if qty_open > 1e-12 and size_pct < 99.5 and latency == 0:
                        for other in lvls:
                            if str(other.get("kind")) == "sl" and str(other.get("status")) == "watching":
                                other["price"] = avg
                                other["ratcheted"] = "breakeven"
                            if str(other.get("kind")) == "trail" and str(other.get("status")) == "pending":
                                other["status"] = "armed"
                                other["peak_price"] = close
                                trail_pct = float(other.get("trail_pct") or 1.5) / 100.0
                                other["price"] = (
                                    close * (1.0 + trail_pct)
                                    if side_n == "short"
                                    else close * (1.0 - trail_pct)
                                )
                elif kind == "add":
                    size_pct = float(lv.get("size_pct") or 50.0) / 100.0
                    schedule_or_run(
                        bar_i=i, kind="add", px=px, fill_qty=qty_initial * size_pct,
                        lv=lv, buy=(side_n == "long"),
                    )

        equity.append(mark_eq(close) if qty_open > 1e-12 else cash_pnl)
        peak_eq = max(peak_eq, equity[-1])

    init = qty_initial * entry
    end = equity[-1] if equity else cash_pnl
    total_ret = (end / init - 1.0) if init > 0 else 0.0
    max_dd = 0.0
    peak = equity[0] if equity else init
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak)

    return ShadowResult(
        bars=len(parsed),
        side=side_n,
        entry=entry,
        qty_initial=qty_initial,
        fills=fills,
        equity=equity,
        total_return=round(total_ret, 6),
        max_drawdown=round(max_dd, 6),
        realized_pnl=round(cash_pnl, 4),
        exit_reason=exit_reason,
        final_qty=round(qty_open, 10),
        final_avg=round(avg, 6) if qty_open > 1e-12 else None,
        avg_slippage=round(sum(slip_samples) / len(slip_samples), 6) if slip_samples else 0.0,
        avg_latency_bars=(
            round(sum(latency_samples) / len(latency_samples), 4)
            if latency_samples
            else float(latency)
        ),
    )
