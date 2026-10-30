"""Paper lot ledger with specific-ID (FIFO / HIFO / min-tax). Not a broker feed."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal, Sequence
from uuid import uuid4

from app.services.construction.tax_lots import Lot

Method = Literal["fifo", "hifo", "min_tax", "specific_id"]


@dataclass(frozen=True, slots=True)
class ClosePick:
    lot_id: str
    qty: float
    cost: float
    acquired: date
    gain: float


def pick_lots(
    lots: Sequence[Lot],
    *,
    symbol: str,
    account: str,
    sleeve_id: str,
    qty: float,
    method: Method = "fifo",
    sale_price: float | None = None,
    specific_ids: Sequence[str] = (),
) -> list[ClosePick]:
    book = [
        L
        for L in lots
        if L.symbol == symbol and L.account == account and L.sleeve_id == sleeve_id and L.qty > 0
    ]
    if method == "specific_id" and specific_ids:
        order = {lid: i for i, lid in enumerate(specific_ids)}
        book = sorted(book, key=lambda L: order.get(L.lot_id, 10_000))
    elif method == "hifo":
        book = sorted(book, key=lambda L: (-L.cost, L.acquired, L.lot_id))
    elif method == "min_tax" and sale_price is not None:
        book = sorted(book, key=lambda L: (float(sale_price) - L.cost, L.acquired, L.lot_id))
    else:
        book = sorted(book, key=lambda L: (L.acquired, L.lot_id))
    left = float(qty)
    out: list[ClosePick] = []
    px = float(sale_price) if sale_price is not None else 0.0
    for lot in book:
        if left <= 1e-12:
            break
        take = min(lot.qty, left)
        out.append(
            ClosePick(
                lot_id=lot.lot_id,
                qty=round(take, 8),
                cost=lot.cost,
                acquired=lot.acquired,
                gain=round((px - lot.cost) * take, 6) if sale_price is not None else 0.0,
            )
        )
        left -= take
    return out


def apply_split(lots: Sequence[Lot], *, symbol: str, ratio: float) -> list[Lot]:
    """Forward split: qty * ratio, cost / ratio. Reverse if ratio < 1."""
    r = float(ratio)
    if r <= 0:
        return list(lots)
    out: list[Lot] = []
    for L in lots:
        if L.symbol != symbol:
            out.append(L)
            continue
        out.append(
            Lot(
                lot_id=L.lot_id,
                symbol=L.symbol,
                qty=round(L.qty * r, 8),
                cost=L.cost / r,
                acquired=L.acquired,
                account=L.account,
                sleeve_id=L.sleeve_id,
                taxable=L.taxable,
            )
        )
    return out


def cash_dividend_usd(lots: Sequence[Lot], *, symbol: str, dps: float) -> float:
    qty = sum(L.qty for L in lots if L.symbol == symbol)
    return round(max(0.0, float(dps)) * qty, 2)


def new_lot(
    *,
    symbol: str,
    qty: float,
    cost: float,
    acquired: date,
    account: str,
    sleeve_id: str,
    taxable: bool = True,
) -> Lot:
    return Lot(
        lot_id=uuid4().hex[:12],
        symbol=symbol.upper(),
        qty=qty,
        cost=cost,
        acquired=acquired,
        account=account,
        sleeve_id=sleeve_id,
        taxable=taxable,
    )


def lots_to_rows(lots: Sequence[Lot]) -> list[dict]:
    rows = []
    for L in lots:
        d = asdict(L)
        d["acquired"] = L.acquired.isoformat()
        rows.append(d)
    return rows
