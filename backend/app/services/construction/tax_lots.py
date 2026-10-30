"""Paper tax lots + IRS-style 30-day wash-sale awareness. Not tax advice."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Sequence


@dataclass(frozen=True, slots=True)
class Lot:
    lot_id: str
    symbol: str
    qty: float
    cost: float
    acquired: date
    account: str  # paper | live
    sleeve_id: str
    taxable: bool = True


@dataclass(frozen=True, slots=True)
class ClosePlan:
    lots: tuple[tuple[str, float], ...]  # lot_id, qty
    wash_blocked: bool
    reason: str


def fifo_lots(lots: Sequence[Lot], *, symbol: str, account: str, sleeve_id: str) -> list[Lot]:
    return sorted(
        [
            L
            for L in lots
            if L.symbol == symbol and L.account == account and L.sleeve_id == sleeve_id and L.qty > 0
        ],
        key=lambda L: (L.acquired, L.lot_id),
    )


def wash_sale_window(as_of: date, *, days: int = 30) -> tuple[date, date]:
    return as_of - timedelta(days=days), as_of + timedelta(days=days)


def would_wash(
    *,
    symbol: str,
    account: str,
    sleeve_id: str,
    loss_sale_on: date,
    replacement_buy_on: date,
    taxable: bool,
) -> bool:
    """Same symbol, same taxable account/sleeve, buy within ±30d of a loss sale."""
    if not taxable:
        return False
    lo, hi = wash_sale_window(loss_sale_on)
    return lo <= replacement_buy_on <= hi and bool(symbol and account and sleeve_id)


def plan_close(
    lots: Sequence[Lot],
    *,
    symbol: str,
    qty: float,
    as_of: date,
    account: str,
    sleeve_id: str,
    sale_is_loss: bool,
    pending_buy: date | None = None,
    method: str = "fifo",
    sale_price: float | None = None,
    specific_ids: Sequence[str] = (),
) -> ClosePlan:
    from app.services.construction.lot_store import pick_lots

    if method in {"hifo", "min_tax", "specific_id"}:
        picked = pick_lots(
            lots,
            symbol=symbol,
            account=account,
            sleeve_id=sleeve_id,
            qty=qty,
            method=method,  # type: ignore[arg-type]
            sale_price=sale_price,
            specific_ids=specific_ids,
        )
        book_ids = [p.lot_id for p in picked]
        book = [
            L
            for lid in book_ids
            for L in lots
            if L.lot_id == lid
        ]
    else:
        book = fifo_lots(lots, symbol=symbol, account=account, sleeve_id=sleeve_id)
    if qty <= 0 or not book:
        return ClosePlan((), False, "nothing_to_close")
    if sale_is_loss and pending_buy and would_wash(
        symbol=symbol,
        account=account,
        sleeve_id=sleeve_id,
        loss_sale_on=as_of,
        replacement_buy_on=pending_buy,
        taxable=book[0].taxable,
    ):
        return ClosePlan((), True, "wash_sale_blocked")
    left = float(qty)
    used: list[tuple[str, float]] = []
    for lot in book:
        take = min(lot.qty, left)
        used.append((lot.lot_id, round(take, 8)))
        left -= take
        if left <= 1e-12:
            break
    if left > 1e-8:
        return ClosePlan(tuple(used), False, "partial_qty")
    return ClosePlan(tuple(used), False, method if method in {"fifo", "hifo", "min_tax", "specific_id"} else "fifo")


def plan_open(
    *,
    symbol: str,
    as_of: date,
    account: str,
    sleeve_id: str,
    recent_loss_sales: Sequence[tuple[str, date, str, str]],
    taxable: bool = True,
) -> tuple[bool, str]:
    """Block a replacement buy if a loss sale sits inside the wash window."""
    if not taxable:
        return True, "non_taxable"
    for sym, sold, acc, slv in recent_loss_sales:
        if would_wash(
            symbol=sym,
            account=acc,
            sleeve_id=slv,
            loss_sale_on=sold,
            replacement_buy_on=as_of,
            taxable=True,
        ) and sym == symbol and acc == account and slv == sleeve_id:
            return False, "wash_sale_blocked"
    return True, "ok"
