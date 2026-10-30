"""Ticker cost basis (Average Buy) — broker-grade book for the desk chart.

Design rules (industry standard: Binance / TV / multi-leg VWAP):
- Average ONLY same-side open legs. Never blend long + short into one Avg.
- Qty weight: Σ(price×qty) / Σ(qty), qty = notional/price (or fill_quantity).
- «In strategy zone» uses entry zone only — never SL/TP (those are risk, not entry).
- Unrealized / break-even use fee-aware math from position_analytics.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import ExecutionOrder, Maneuver, ManeuverStatus, SignalDirection
from app.services.portfolio.position_analytics import (
    finite_float,
    latest_prices,
    maneuver_stop_loss,
    maneuver_take_profit,
    position_quantity,
)
from app.services.portfolio.user_scope import maneuvers_for_user

logger = get_logger(__name__)

OPEN_BOOK = (ManeuverStatus.FILLED, ManeuverStatus.EXECUTING)
HISTORY = (ManeuverStatus.FILLED, ManeuverStatus.EXECUTING, ManeuverStatus.CLOSED)


@dataclass
class TradeMarker:
    maneuver_id: str
    side: str  # buy | sell
    kind: str  # entry | exit
    price: float
    at: str
    size_usd: float
    qty: float | None = None
    label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "maneuver_id": self.maneuver_id,
            "side": self.side,
            "kind": self.kind,
            "price": self.price,
            "at": self.at,
            "size_usd": self.size_usd,
            "qty": self.qty,
            "label": self.label,
        }


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _direction_sign(direction: Any) -> int:
    raw = direction.value if hasattr(direction, "value") else str(direction or "")
    return -1 if raw.lower() == SignalDirection.SHORT.value else 1


def _entry_side(direction: Any) -> str:
    return "sell" if _direction_sign(direction) < 0 else "buy"


def _exit_side(direction: Any) -> str:
    return "buy" if _direction_sign(direction) < 0 else "sell"


def _leg_qty(m: Maneuver, fill_qty: float | None = None) -> float | None:
    if fill_qty is not None and fill_qty > 0:
        return float(fill_qty)
    return position_quantity(m)


def _leg_price(m: Maneuver) -> float | None:
    px = finite_float(m.fill_price) or finite_float(m.entry_price)
    if px is None or px <= 0:
        return None
    return px


def weighted_avg_entry(maneuvers: list[Maneuver], qty_by_id: dict[str, float] | None = None) -> float | None:
    """Same-side VWAP: Σ(price×qty)/Σ(qty)."""
    notional = 0.0
    qty_sum = 0.0
    for m in maneuvers:
        px = _leg_price(m)
        qty = (qty_by_id or {}).get(m.id) if qty_by_id else None
        if qty is None:
            qty = _leg_qty(m)
        if px is None or qty is None or qty <= 0:
            continue
        notional += px * qty
        qty_sum += qty
    if qty_sum <= 0:
        return None
    return round(notional / qty_sum, 6)


def entry_zone_range(maneuvers: list[Maneuver]) -> tuple[float | None, float | None]:
    """Strategy entry band only (no SL/TP pollution)."""
    lows: list[float] = []
    highs: list[float] = []
    for m in maneuvers:
        lo = finite_float(m.entry_zone_low)
        hi = finite_float(m.entry_zone_high)
        if lo is not None:
            lows.append(lo)
        if hi is not None:
            highs.append(hi)
    if not lows and not highs:
        return None, None
    if lows and highs:
        return min(lows), max(highs)
    if lows:
        return min(lows), min(lows)
    return max(highs), max(highs)


def barrier_envelope(maneuvers: list[Maneuver]) -> tuple[float | None, float | None]:
    """Outer SL/TP envelope for chart risk lines (separate from entry zone)."""
    vals: list[float] = []
    for m in maneuvers:
        for v in (maneuver_stop_loss(m), maneuver_take_profit(m)):
            if v is not None:
                vals.append(v)
    if not vals:
        return None, None
    return min(vals), max(vals)


def fee_adjusted_breakeven(
    avg: float,
    *,
    side: str,
    qty: float | None = None,
    fee_usd: float = 0.0,
    funding_usd: float = 0.0,
) -> float:
    """Break-even price after round-trip commission + accrued funding.

    When ``qty`` and absolute costs are known, BE is shifted by
    (entry_fees_allocated + expected_exit_fee + funding) / qty.
    Otherwise falls back to percent round-trip on avg.
    """
    rate = max(float(settings.COMMISSION_RATE_PCT or 0.0), 0.0) / 100.0
    if qty is not None and qty > 0:
        notional = abs(avg * qty)
        exit_fee = notional * rate
        entry_fee = max(float(fee_usd or 0.0), 0.0)
        # funding_usd: positive = cost already paid by the book
        cost = entry_fee + exit_fee + max(float(funding_usd or 0.0), 0.0)
        shift = cost / qty
        if side == "short":
            return round(avg - shift, 6)
        return round(avg + shift, 6)
    rt = rate * 2.0
    if side == "short":
        return round(avg * (1.0 - rt), 6)
    return round(avg * (1.0 + rt), 6)


def unrealized_vs_avg(
    avg: float,
    mark: float,
    qty: float,
    *,
    side: str,
) -> tuple[float, float]:
    """Return (pnl_usd, pnl_pct) vs Average Buy at mark."""
    if avg <= 0 or qty <= 0 or mark <= 0:
        return 0.0, 0.0
    if side == "short":
        pnl = (avg - mark) * qty
        pct = (avg - mark) / avg * 100.0
    else:
        pnl = (mark - avg) * qty
        pct = (mark - avg) / avg * 100.0
    return round(pnl, 2), round(pct, 3)


def _fmt_price_label(price: float | None) -> str:
    if price is None:
        return "—"
    if price >= 1000:
        return f"{price:,.0f}"
    if price >= 1:
        return f"{price:.2f}"
    return f"{price:.4f}"


def build_markers(maneuvers: list[Maneuver], *, limit: int = 120) -> list[TradeMarker]:
    markers: list[TradeMarker] = []
    for m in maneuvers:
        size = float(m.position_size_usd or 0.0)
        qty = _leg_qty(m)
        fill = _leg_price(m)
        filled_at = _iso(m.filled_at) or _iso(m.approved_at) or _iso(m.created_at)
        if fill is not None and filled_at:
            side = _entry_side(m.direction)
            markers.append(
                TradeMarker(
                    maneuver_id=m.id,
                    side=side,
                    kind="entry",
                    price=fill,
                    at=filled_at,
                    size_usd=size,
                    qty=qty,
                    label=f"{'B' if side == 'buy' else 'S'} {_fmt_price_label(fill)}",
                )
            )
        exit_px = finite_float(m.exit_price)
        closed_at = _iso(m.closed_at)
        if m.status == ManeuverStatus.CLOSED and exit_px and exit_px > 0 and closed_at:
            side = _exit_side(m.direction)
            reason = str(m.exit_reason or "")
            tag = "X"
            if reason == "take_profit":
                tag = "TP"
            elif reason == "stop":
                tag = "SL"
            elif reason == "expiration":
                tag = "Exp"
            markers.append(
                TradeMarker(
                    maneuver_id=m.id,
                    side=side,
                    kind="exit",
                    price=exit_px,
                    at=closed_at,
                    size_usd=size,
                    qty=qty,
                    label=f"{tag} {_fmt_price_label(exit_px)}",
                )
            )
        # Robot Core add fills recorded on the maneuver
        meta = getattr(m, "signal_meta", None)
        meta = meta if isinstance(meta, dict) else {}
        for fill in meta.get("robot_fills") or []:
            if not isinstance(fill, dict):
                continue
            px = finite_float(fill.get("price"))
            at = fill.get("at")
            if px is None or px <= 0 or not isinstance(at, str) or not at:
                continue
            side = _entry_side(m.direction)
            usd = float(fill.get("usd") or 0.0)
            q = finite_float(fill.get("qty"))
            fill_kind = str(fill.get("kind") or "add")
            if fill_kind in {"tp_partial", "reduce"}:
                side = _exit_side(m.direction)
                label = f"TP½ {_fmt_price_label(px)}"
                kind_out = "exit"
            elif fill_kind == "add":
                label = f"Add {_fmt_price_label(px)}"
                kind_out = "add"
            else:
                label = f"{fill_kind} {_fmt_price_label(px)}"
                kind_out = fill_kind
            markers.append(
                TradeMarker(
                    maneuver_id=m.id,
                    side=side,
                    kind=kind_out,
                    price=px,
                    at=at,
                    size_usd=usd,
                    qty=q,
                    label=label,
                )
            )
    markers.sort(key=lambda x: x.at)
    return markers[-limit:]


async def _fill_qty_map(db: AsyncSession, maneuver_ids: list[str]) -> dict[str, float]:
    if not maneuver_ids:
        return {}
    from sqlalchemy import select

    result = await db.execute(
        select(ExecutionOrder).where(
            ExecutionOrder.maneuver_id.in_(maneuver_ids),
            ExecutionOrder.status == "filled",
        )
    )
    out: dict[str, float] = {}
    for row in result.scalars().all():
        q = finite_float(row.fill_quantity) or finite_float(row.quantity)
        if q is None or q <= 0:
            continue
        out[row.maneuver_id] = out.get(row.maneuver_id, 0.0) + q
    return out


async def ticker_book(
    db: AsyncSession,
    user_id: str,
    ticker: str,
    *,
    staff_include_orphans: bool = False,
) -> dict[str, Any]:
    sym = ticker.strip().upper()
    raw = ticker.strip()
    stmt = (
        maneuvers_for_user(user_id, staff_include_orphans=staff_include_orphans)
        .where(or_(Maneuver.ticker == sym, Maneuver.ticker == raw))
        .where(Maneuver.status.in_(HISTORY))
        .options(joinedload(Maneuver.report))
        .order_by(Maneuver.created_at.desc())
        .limit(300)
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().unique().all())

    open_legs = [m for m in rows if m.status in OPEN_BOOK and _leg_price(m) is not None]
    long_legs = [m for m in open_legs if _direction_sign(m.direction) > 0]
    short_legs = [m for m in open_legs if _direction_sign(m.direction) < 0]

    qty_map = await _fill_qty_map(db, [m.id for m in open_legs])

    # Prefer LotLedger when present (Robot Core truth).
    lot_avg = None
    lot_be = None
    lot_qty = None
    lot_side = None
    lot_avg_long = None
    lot_avg_short = None
    lot_be_long = None
    lot_be_short = None
    lot_qty_long = None
    lot_qty_short = None
    lot_dual = False
    try:
        from app.services.portfolio.lot_ledger import book_snapshot

        # Savepoint: a failing lot-ledger query must not abort the whole request transaction.
        async with db.begin_nested():
            snap = await book_snapshot(db, user_id=user_id, ticker=sym)
        q_long = snap.qty_long
        q_short = snap.qty_short
        has_long = q_long is not None and q_long > 0
        has_short = q_short is not None and q_short > 0
        has_net = snap.avg_entry is not None and snap.qty is not None and snap.qty > 0
        if has_long or has_short or has_net:
            lot_avg = snap.avg_entry
            lot_be = snap.breakeven
            lot_qty = snap.qty
            if snap.side != "dual":
                lot_side = snap.side
            elif q_long is None or q_short is None:
                lot_side = None
            else:
                lot_side = "long" if q_long >= q_short else "short"
            lot_avg_long = snap.avg_long
            lot_avg_short = snap.avg_short
            lot_be_long = snap.breakeven_long
            lot_be_short = snap.breakeven_short
            lot_qty_long = snap.qty_long
            lot_qty_short = snap.qty_short
            lot_dual = bool(snap.dual)
    except Exception as exc:
        logger.warning("lot snapshot unavailable; use fill-weighted basis", ticker=sym, error=str(exc)[:200])

    avg_long = lot_avg_long if lot_avg_long is not None else weighted_avg_entry(long_legs, qty_map)
    avg_short = lot_avg_short if lot_avg_short is not None else weighted_avg_entry(short_legs, qty_map)
    qty_long = sum((qty_map.get(m.id) or _leg_qty(m) or 0.0) for m in long_legs)
    qty_short = sum((qty_map.get(m.id) or _leg_qty(m) or 0.0) for m in short_legs)
    long_usd = round(sum(float(m.position_size_usd or 0) for m in long_legs), 2)
    short_usd = round(sum(float(m.position_size_usd or 0) for m in short_legs), 2)

    # Dominant book = larger USD exposure (broker UI shows one primary Avg).
    # LotLedger overrides when Robot Core has open lots for this ticker.
    if lot_avg is not None and lot_qty and lot_qty > 0 and lot_side in ("long", "short"):
        net_side = lot_side
        avg = lot_avg
        active_qty = float(lot_qty)
        active_legs = long_legs if lot_side == "long" else short_legs
        if not active_legs:
            active_legs = open_legs
    elif long_usd >= short_usd and avg_long is not None:
        net_side = "long"
        avg = avg_long
        active_legs = long_legs
        active_qty = qty_long
    elif avg_short is not None:
        net_side = "short"
        avg = avg_short
        active_legs = short_legs
        active_qty = qty_short
    else:
        net_side = "flat"
        avg = None
        active_legs = []
        active_qty = 0.0

    zone_src = active_legs or open_legs or rows[:8]
    zone_lo, zone_hi = entry_zone_range(zone_src)
    risk_lo, risk_hi = barrier_envelope(active_legs or open_legs)

    in_zone = None
    zone_edge_pct = None
    if avg is not None and zone_lo is not None and zone_hi is not None:
        lo, hi = min(zone_lo, zone_hi), max(zone_lo, zone_hi)
        in_zone = lo <= avg <= hi
        mid = (lo + hi) / 2.0 if hi > lo else lo
        if mid > 0:
            zone_edge_pct = round((avg - mid) / mid * 100.0, 3)

    prices = await latest_prices(db, [sym, raw])
    mark = prices.get(sym) or prices.get(raw.upper()) or prices.get(raw)
    unrealized_usd = None
    unrealized_pct = None
    breakeven = lot_be if lot_avg is not None else None
    if avg is not None and mark is not None and active_qty > 0 and net_side in ("long", "short"):
        unrealized_usd, unrealized_pct = unrealized_vs_avg(
            avg, float(mark), active_qty, side=net_side
        )
        if breakeven is None:
            breakeven = fee_adjusted_breakeven(
                avg, side=net_side, qty=active_qty if active_qty > 0 else None
            )

    legs_out = []
    for m in open_legs:
        px = _leg_price(m)
        q = qty_map.get(m.id) or _leg_qty(m)
        legs_out.append(
            {
                "maneuver_id": m.id,
                "side": "long" if _direction_sign(m.direction) > 0 else "short",
                "fill_price": px,
                "size_usd": float(m.position_size_usd or 0),
                "qty": q,
                "stop_loss": maneuver_stop_loss(m),
                "take_profit": maneuver_take_profit(m),
                "filled_at": _iso(m.filled_at),
            }
        )

    return {
        "ticker": sym,
        "avg_entry": avg,
        "avg_long": avg_long,
        "avg_short": avg_short,
        "qty": round(active_qty, 8) if active_qty else 0.0,
        "qty_long": round(float(lot_qty_long) if lot_qty_long is not None else qty_long, 8),
        "qty_short": round(float(lot_qty_short) if lot_qty_short is not None else qty_short, 8),
        "exposure_usd": round(long_usd + short_usd, 2),
        "long_usd": long_usd,
        "short_usd": short_usd,
        "open_legs": len(open_legs),
        "net_side": "dual" if lot_dual else net_side,
        "dual": lot_dual,
        "mark_price": mark,
        "breakeven": breakeven,
        "breakeven_long": lot_be_long,
        "breakeven_short": lot_be_short,
        "unrealized_usd": unrealized_usd,
        "unrealized_pct": unrealized_pct,
        "strategy_low": zone_lo,
        "strategy_high": zone_hi,
        "risk_low": risk_lo,
        "risk_high": risk_hi,
        "avg_in_strategy_zone": in_zone,
        "zone_edge_pct": zone_edge_pct,
        "legs": legs_out,
        "markers": [m.to_dict() for m in build_markers(rows)],
        "pnl_if_flat_hint": (
            (
                f"Long {_fmt_price_label(avg_long)} · Short {_fmt_price_label(avg_short)}"
                if lot_dual and avg_long is not None and avg_short is not None
                else (
                    f"Avg {net_side} {_fmt_price_label(avg)} · BE {_fmt_price_label(breakeven)}"
                    if avg is not None and breakeven is not None
                    else (
                        f"Avg {net_side} {_fmt_price_label(avg)}"
                        if avg is not None
                        else "нет открытых ног с зафиксированным входом"
                    )
                )
            )
        ),
    }
