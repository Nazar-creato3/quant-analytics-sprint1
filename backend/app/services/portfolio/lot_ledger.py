"""Lot ledger — broker-grade inventory for Average Buy and FIFO realized P&L.

Ethical boundary: no spoofing / wash / front-run helpers. Ledger is truth for
paper and live fills recorded by the execution router.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.robot_models import LotCloseEvent, PositionLot
from app.utils.json_safe import coerce_finite_float

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fee_usd(notional: float) -> float:
    rate = max(float(settings.COMMISSION_RATE_PCT or 0.0), 0.0) / 100.0
    return round(abs(notional) * rate, 6)


@dataclass
class SideBook:
    qty: float = 0.0
    avg_entry: float | None = None
    cost_basis_usd: float = 0.0
    fee_usd: float = 0.0
    funding_usd: float = 0.0
    open_lots: int = 0
    breakeven: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "qty": self.qty,
            "avg_entry": self.avg_entry,
            "cost_basis_usd": self.cost_basis_usd,
            "fee_usd": self.fee_usd,
            "funding_usd": self.funding_usd,
            "open_lots": self.open_lots,
            "breakeven": self.breakeven,
        }


@dataclass
class BookSnapshot:
    ticker: str
    side: str  # long | short | flat | dual
    qty: float
    avg_entry: float | None
    cost_basis_usd: float
    fee_usd: float
    open_lots: int
    breakeven: float | None
    lots: list[dict[str, Any]]
    funding_usd: float = 0.0
    avg_long: float | None = None
    avg_short: float | None = None
    qty_long: float = 0.0
    qty_short: float = 0.0
    breakeven_long: float | None = None
    breakeven_short: float | None = None
    net_breakeven: float | None = None
    dual: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "side": self.side,
            "qty": self.qty,
            "avg_entry": self.avg_entry,
            "cost_basis_usd": self.cost_basis_usd,
            "fee_usd": self.fee_usd,
            "funding_usd": self.funding_usd,
            "open_lots": self.open_lots,
            "breakeven": self.breakeven,
            "lots": self.lots,
            "avg_long": self.avg_long,
            "avg_short": self.avg_short,
            "qty_long": self.qty_long,
            "qty_short": self.qty_short,
            "breakeven_long": self.breakeven_long,
            "breakeven_short": self.breakeven_short,
            "net_breakeven": self.net_breakeven,
            "dual": self.dual,
        }


def _funding_accrued_usd(*, notional: float, opened_at: datetime | None, side: str) -> float:
    """Estimate funding drag on open notional since lot open (crypto perps)."""
    rate = max(float(getattr(settings, "FUNDING_RATE_PCT_PER_DAY", 0.0) or 0.0), 0.0) / 100.0
    if rate <= 0 or notional <= 0 or opened_at is None:
        return 0.0
    opened = opened_at if opened_at.tzinfo else opened_at.replace(tzinfo=timezone.utc)
    days = max((_now() - opened).total_seconds() / 86400.0, 0.0)
    # Both sides accrue as cost estimate for BE (conservative desk view).
    return round(abs(notional) * rate * days, 6)


def _side_book_from_lots(lots: list[Any], *, side: str) -> SideBook:
    from app.services.portfolio.cost_basis import fee_adjusted_breakeven

    if not lots:
        return SideBook()
    notional = 0.0
    qty = 0.0
    fees = 0.0
    funding = 0.0
    for l in lots:
        q = float(l.qty_open)
        px = float(l.entry_price)
        notional += px * q
        qty += q
        fee_slice = float(l.fee_usd) * (q / max(float(l.qty_initial), 1e-12))
        fees += fee_slice
        funding += _funding_accrued_usd(notional=px * q, opened_at=l.opened_at, side=side)
        # Optional explicit funding in meta
        meta = l.meta if isinstance(getattr(l, "meta", None), dict) else {}
        funding += max(float(meta.get("funding_usd") or 0.0), 0.0) * (
            q / max(float(l.qty_initial), 1e-12)
        )
    avg = round(notional / qty, 6) if qty > 0 else None
    be = None
    if avg is not None and qty > 0:
        be = fee_adjusted_breakeven(
            avg, side=side, qty=qty, fee_usd=fees, funding_usd=funding
        )
    return SideBook(
        qty=round(qty, 10),
        avg_entry=avg,
        cost_basis_usd=round(notional, 4),
        fee_usd=round(fees, 6),
        funding_usd=round(funding, 6),
        open_lots=len(lots),
        breakeven=be,
    )


async def open_lot(
    db: AsyncSession,
    *,
    user_id: str,
    ticker: str,
    side: str,
    qty: float,
    price: float,
    source: str = "maneuver",
    maneuver_id: str | None = None,
    robot_plan_id: str | None = None,
    fee_usd: float | None = None,
    meta: dict[str, Any] | None = None,
) -> PositionLot:
    side_n = "short" if str(side).lower() in {"short", "sell"} else "long"
    q = abs(float(qty))
    px = float(price)
    if q <= 0 or px <= 0:
        raise ValueError("qty and price must be positive")
    fee = float(fee_usd) if fee_usd is not None else _fee_usd(q * px)
    lot = PositionLot(
        user_id=user_id,
        ticker=ticker.strip().upper(),
        side=side_n,
        qty_open=q,
        qty_initial=q,
        entry_price=px,
        fee_usd=fee,
        source=source,
        maneuver_id=maneuver_id,
        robot_plan_id=robot_plan_id,
        status="open",
        meta=meta or {},
        opened_at=_now(),
    )
    db.add(lot)
    await db.flush()
    logger.info(
        "lot_opened",
        lot_id=lot.id,
        ticker=lot.ticker,
        side=side_n,
        qty=q,
        price=px,
        source=source,
    )
    return lot


async def reduce_lots_fifo(
    db: AsyncSession,
    *,
    user_id: str,
    ticker: str,
    side: str,
    qty: float,
    exit_price: float,
    reason: str = "manual",
    maneuver_id: str | None = None,
    fee_usd: float | None = None,
) -> dict[str, Any]:
    """Close ``qty`` of same-side open lots FIFO. Returns realized summary."""
    side_n = "short" if str(side).lower() in {"short", "sell"} else "long"
    remaining = abs(float(qty))
    px = float(exit_price)
    if remaining <= 0 or px <= 0:
        raise ValueError("qty and exit_price must be positive")

    stmt = (
        select(PositionLot)
        .where(
            PositionLot.user_id == user_id,
            PositionLot.ticker == ticker.strip().upper(),
            PositionLot.side == side_n,
            PositionLot.status == "open",
            PositionLot.qty_open > 0,
        )
        .order_by(PositionLot.opened_at.asc())
    )
    result = await db.execute(stmt)
    lots = list(result.scalars().all())
    realized = 0.0
    closed_qty = 0.0
    events: list[LotCloseEvent] = []
    exit_fee_total = float(fee_usd) if fee_usd is not None else _fee_usd(remaining * px)
    fee_left = exit_fee_total

    for lot in lots:
        if remaining <= 1e-12:
            break
        take = min(float(lot.qty_open), remaining)
        if take <= 0:
            continue
        if side_n == "long":
            pnl = (px - float(lot.entry_price)) * take
        else:
            pnl = (float(lot.entry_price) - px) * take
        # Allocate exit fee proportionally; entry fee already on lot.
        fee_slice = min(fee_left, exit_fee_total * (take / max(remaining, take)))
        fee_left = max(0.0, fee_left - fee_slice)
        entry_fee_slice = float(lot.fee_usd) * (take / max(float(lot.qty_initial), 1e-12))
        pnl_net = pnl - fee_slice - entry_fee_slice
        realized += pnl_net
        closed_qty += take
        remaining -= take
        lot.qty_open = round(float(lot.qty_open) - take, 10)
        if lot.qty_open <= 1e-10:
            lot.qty_open = 0.0
            lot.status = "closed"
            lot.closed_at = _now()
        ev = LotCloseEvent(
            user_id=user_id,
            ticker=lot.ticker,
            lot_id=lot.id,
            qty=take,
            exit_price=px,
            realized_pnl=round(pnl_net, 4),
            fee_usd=round(fee_slice + entry_fee_slice, 6),
            reason=reason,
            maneuver_id=maneuver_id,
            created_at=_now(),
        )
        db.add(ev)
        events.append(ev)

    await db.flush()
    return {
        "closed_qty": round(closed_qty, 10),
        "remaining_requested": round(max(remaining, 0.0), 10),
        "realized_pnl": round(realized, 4),
        "events": len(events),
    }


async def book_snapshot(
    db: AsyncSession,
    *,
    user_id: str,
    ticker: str,
    side: str | None = None,
) -> BookSnapshot:
    sym = ticker.strip().upper()
    stmt = select(PositionLot).where(
        PositionLot.user_id == user_id,
        PositionLot.ticker == sym,
        PositionLot.status == "open",
        PositionLot.qty_open > 0,
    )
    if side:
        side_n = "short" if str(side).lower() in {"short", "sell"} else "long"
        stmt = stmt.where(PositionLot.side == side_n)
    result = await db.execute(stmt.order_by(PositionLot.opened_at.asc()))
    lots = list(result.scalars().all())

    long_lots = [l for l in lots if l.side == "long"]
    short_lots = [l for l in lots if l.side == "short"]
    long_b = _side_book_from_lots(long_lots, side="long")
    short_b = _side_book_from_lots(short_lots, side="short")

    dual = long_b.qty > 0 and short_b.qty > 0
    if dual:
        net_side = "dual"
        # Dominant for primary Avg = larger notional
        if long_b.cost_basis_usd >= short_b.cost_basis_usd:
            primary = long_b
            primary_side = "long"
            active = long_lots
        else:
            primary = short_b
            primary_side = "short"
            active = short_lots
    elif long_b.qty > 0:
        net_side = primary_side = "long"
        primary = long_b
        active = long_lots
    elif short_b.qty > 0:
        net_side = primary_side = "short"
        primary = short_b
        active = short_lots
    else:
        return BookSnapshot(
            ticker=sym,
            side="flat",
            qty=0.0,
            avg_entry=None,
            cost_basis_usd=0.0,
            fee_usd=0.0,
            open_lots=0,
            breakeven=None,
            lots=[],
        )

    rows: list[dict[str, Any]] = []
    for l in lots:  # both sides for dual transparency
        q = float(l.qty_open)
        px = float(l.entry_price)
        rows.append(
            {
                "id": l.id,
                "side": l.side,
                "qty_open": q,
                "entry_price": px,
                "opened_at": l.opened_at.isoformat() if l.opened_at else None,
                "maneuver_id": l.maneuver_id,
                "source": l.source,
            }
        )

    # Prefer recorded funding_events over constant accrual when present
    try:
        from app.services.robot.funding import funding_sum_for_user_ticker

        ev_funding = await funding_sum_for_user_ticker(db, user_id=user_id, ticker=sym)
        if ev_funding > 0:
            # Rebuild BE with event funding split by side qty
            total_qty = long_b.qty + short_b.qty
            if total_qty > 0 and long_b.qty > 0:
                long_b.funding_usd = ev_funding * (long_b.qty / total_qty)
                if long_b.avg_entry and long_b.qty > 0:
                    from app.services.portfolio.cost_basis import fee_adjusted_breakeven

                    long_b.breakeven = fee_adjusted_breakeven(
                        long_b.avg_entry,
                        side="long",
                        qty=long_b.qty,
                        fee_usd=long_b.fee_usd,
                        funding_usd=long_b.funding_usd,
                    )
            if total_qty > 0 and short_b.qty > 0:
                short_b.funding_usd = ev_funding * (short_b.qty / total_qty)
                if short_b.avg_entry and short_b.qty > 0:
                    from app.services.portfolio.cost_basis import fee_adjusted_breakeven

                    short_b.breakeven = fee_adjusted_breakeven(
                        short_b.avg_entry,
                        side="short",
                        qty=short_b.qty,
                        fee_usd=short_b.fee_usd,
                        funding_usd=short_b.funding_usd,
                    )
            primary = long_b if primary_side == "long" else short_b
    except Exception as exc:
        logger.warning("funding events unavailable; keep prior breakeven", ticker=sym, error=str(exc)[:200])

    net_be = None
    if dual and long_b.breakeven and short_b.breakeven and (long_b.qty + short_b.qty) > 0:
        net_be = round(
            (long_b.breakeven * long_b.qty + short_b.breakeven * short_b.qty)
            / (long_b.qty + short_b.qty),
            6,
        )
    elif primary.breakeven is not None:
        net_be = primary.breakeven

    return BookSnapshot(
        ticker=sym,
        side=net_side,
        qty=primary.qty,
        avg_entry=primary.avg_entry,
        cost_basis_usd=primary.cost_basis_usd,
        fee_usd=round(long_b.fee_usd + short_b.fee_usd, 6),
        funding_usd=round(long_b.funding_usd + short_b.funding_usd, 6),
        open_lots=long_b.open_lots + short_b.open_lots,
        breakeven=primary.breakeven,
        lots=rows,
        avg_long=long_b.avg_entry,
        avg_short=short_b.avg_entry,
        qty_long=long_b.qty,
        qty_short=short_b.qty,
        breakeven_long=long_b.breakeven,
        breakeven_short=short_b.breakeven,
        net_breakeven=net_be,
        dual=dual,
    )


async def record_maneuver_fill(
    db: AsyncSession,
    *,
    user_id: str,
    maneuver_id: str,
    ticker: str,
    direction: str,
    fill_price: float,
    qty: float,
    robot_plan_id: str | None = None,
) -> PositionLot | None:
    """Idempotent: skip if a lot already exists for this maneuver_id."""
    existing = await db.execute(
        select(PositionLot).where(PositionLot.maneuver_id == maneuver_id).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        return None
    px = coerce_finite_float(fill_price, 0.0)
    q = coerce_finite_float(qty, 0.0)
    if px <= 0 or q <= 0:
        return None
    return await open_lot(
        db,
        user_id=user_id,
        ticker=ticker,
        side=direction,
        qty=q,
        price=px,
        source="maneuver",
        maneuver_id=maneuver_id,
        robot_plan_id=robot_plan_id,
    )


async def close_maneuver_lots(
    db: AsyncSession,
    *,
    user_id: str,
    maneuver_id: str,
    ticker: str,
    direction: str,
    exit_price: float,
    reason: str,
) -> dict[str, Any]:
    """Close lots tied to this maneuver (preferred), else FIFO by side."""
    result = await db.execute(
        select(PositionLot).where(
            PositionLot.user_id == user_id,
            PositionLot.maneuver_id == maneuver_id,
            PositionLot.status == "open",
            PositionLot.qty_open > 0,
        )
    )
    lots = list(result.scalars().all())
    if lots:
        qty = sum(float(l.qty_open) for l in lots)
        return await reduce_lots_fifo(
            db,
            user_id=user_id,
            ticker=ticker,
            side=direction,
            qty=qty,
            exit_price=exit_price,
            reason=reason,
            maneuver_id=maneuver_id,
        )
    # Fallback: nothing linked — no-op rather than guessing wrong inventory
    return {"closed_qty": 0.0, "remaining_requested": 0.0, "realized_pnl": 0.0, "events": 0}
