"""Reconcile maneuver notional with LotLedger after every robot fill."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.logging import get_logger
from app.db.models import Maneuver
from app.services.portfolio.lot_ledger import book_snapshot
from app.services.portfolio.position_analytics import finite_float

logger = get_logger(__name__)


class ReconcileError(Exception):
    """Ledger and maneuver diverged beyond tolerance."""


async def reconcile_maneuver_with_ledger(
    db: AsyncSession,
    *,
    maneuver_id: str,
    user_id: str,
    mark_price: float | None = None,
    tolerance_qty: float = 1e-6,
    block_on_diverge: bool = False,
) -> dict[str, Any]:
    """Align maneuver.position_size_usd with open lots for this ticker/side.

    After partial TP / add, ledger is truth — rewrite notional from lots.
    """
    maneuver = await db.get(Maneuver, maneuver_id)
    if maneuver is None:
        return {"ok": False, "error": "maneuver_not_found"}

    side = str(getattr(maneuver.direction, "value", maneuver.direction) or "long").lower()
    side_n = "short" if side == "short" else "long"
    snap = await book_snapshot(
        db, user_id=user_id, ticker=maneuver.ticker, side=side_n
    )

    entry = finite_float(maneuver.fill_price) or finite_float(maneuver.entry_price)
    if snap.qty <= tolerance_qty:
        # Flat book — size should be ~0 if still open (caller closes separately)
        expected_usd = 0.0
    elif snap.avg_entry and snap.avg_entry > 0:
        expected_usd = round(snap.qty * snap.avg_entry, 4)
    elif entry and entry > 0:
        expected_usd = round(snap.qty * entry, 4)
    else:
        expected_usd = float(maneuver.position_size_usd or 0.0)

    prev = float(maneuver.position_size_usd or 0.0)
    delta = abs(prev - expected_usd)
    diverged = delta > max(0.01, abs(prev) * 0.001) and snap.qty > tolerance_qty

    if diverged:
        logger.warning(
            "maneuver_ledger_diverge",
            maneuver_id=maneuver_id,
            prev_usd=prev,
            ledger_usd=expected_usd,
            ledger_qty=snap.qty,
        )
        if block_on_diverge:
            meta = dict(maneuver.signal_meta or {}) if isinstance(maneuver.signal_meta, dict) else {}
            meta["robot_block_adds"] = True
            meta["robot_block_reason"] = "ledger_diverge"
            maneuver.signal_meta = meta
            flag_modified(maneuver, "signal_meta")
            raise ReconcileError(
                f"maneuver {maneuver_id} size {prev} vs ledger {expected_usd}"
            )

    # Always write ledger truth when we have open qty
    if snap.qty > tolerance_qty:
        maneuver.position_size_usd = expected_usd
        meta = dict(maneuver.signal_meta or {}) if isinstance(maneuver.signal_meta, dict) else {}
        meta["ledger_qty"] = snap.qty
        meta["ledger_avg"] = snap.avg_entry
        meta["ledger_be"] = snap.breakeven
        meta["ledger_reconciled"] = True
        if mark_price and snap.avg_entry and snap.qty > 0:
            if side_n == "short":
                upnl = (snap.avg_entry - float(mark_price)) * snap.qty
            else:
                upnl = (float(mark_price) - snap.avg_entry) * snap.qty
            meta["ledger_unrealized"] = round(upnl, 4)
        maneuver.signal_meta = meta
        try:
            flag_modified(maneuver, "signal_meta")
        except Exception:
            pass

    return {
        "ok": True,
        "maneuver_id": maneuver_id,
        "prev_usd": prev,
        "ledger_usd": expected_usd,
        "ledger_qty": snap.qty,
        "diverged": diverged,
    }
