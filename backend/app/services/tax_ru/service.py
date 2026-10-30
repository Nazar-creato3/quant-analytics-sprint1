"""K3 tax estimates for a session book. Demo/paper only; [ЮРИСТ] flag.

Methodology: docs/methodology/tax.md. Numbers from target_portfolio.tax.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from time import perf_counter
from typing import Any

from app.services.explanations.service import filter_wording
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import is_enabled
from app.services.tax_ru.math import (
    NO_DATA,
    iis_block,
    loss_harvest_rows,
    position_lth_row,
    year_ndfl_estimate,
)
from app.services.tax_ru.rates import rates_snapshot
from app.services.target_portfolio.tax import NDFL_RATE_LABEL, fifo_realize
from app.services.target_portfolio.types import TaxLot

METHOD = "/methodology/tax"
LAWYER = "[ЮРИСТ]"
CAPTION = "расчёт по вашим позициям и прошлым сделкам, не налоговая консультация"


def _empty(reason: str, *, elapsed_ms: float | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "data_status": NO_DATA,
        "reason": reason,
        "lth": [],
        "year": None,
        "loss_harvest": [],
        "iis": None,
        "rates": rates_snapshot(),
        "methodology": METHOD,
        "lawyer_gate": LAWYER,
        "caption": CAPTION,
        "demo_only": True,
        "as_of": date.today().isoformat(),
        "source": "данные портфеля",
    }
    if elapsed_ms is not None:
        out["elapsed_ms"] = elapsed_ms
    return out


def _open_lots(user_id: str, mode: str) -> list[TaxLot]:
    """Reuse act_desk FIFO lot reconstruction from book trades."""
    from app.services.act_desk.service import _open_tax_lots

    raw = _open_tax_lots(get_book().transactions(user_id=user_id, mode=mode))  # type: ignore[arg-type]
    return [
        TaxLot(
            lot_id=str(row["lot_id"]),
            ticker=str(row["ticker"]),
            qty=Decimal(str(row["qty"])),
            cost=Decimal(str(row["cost"])),
            acquired=row["acquired"] if isinstance(row["acquired"], date) else date.fromisoformat(str(row["acquired"])),
        )
        for row in raw
    ]


def _marks(user_id: str, mode: str) -> dict[str, Decimal]:
    from app.services.concentration.service import _trade_price

    positions = get_book().positions(user_id=user_id, mode=mode)  # type: ignore[arg-type]
    out: dict[str, Decimal] = {}
    for pos in positions:
        ticker = (pos.ticker or "").upper()
        if not ticker or ticker == "CASH":
            continue
        px = _trade_price(user_id, mode, ticker)
        if px is not None:
            out[ticker] = Decimal(str(px))
    return out


def _realized_year(user_id: str, mode: str, year: int) -> list[dict[str, str]]:
    """Rebuild sells within ``year`` against FIFO open lots from prior buys."""
    from app.services.portfolio_book.store import Transaction

    txns = list(get_book().transactions(user_id=user_id, mode=mode))  # type: ignore[arg-type]
    ordered = sorted(txns, key=lambda row: (row.event_time, row.id))
    lots: dict[str, list[TaxLot]] = {}
    seq = 0
    realized: list[dict[str, str]] = []
    for row in ordered:
        if not isinstance(row, Transaction) or row.kind != "trade" or row.qty == 0:
            continue
        ticker = row.ticker.upper()
        day = row.event_time.date() if hasattr(row.event_time, "date") else date.today()
        bucket = lots.setdefault(ticker, [])
        if row.qty > 0:
            seq += 1
            bucket.append(
                TaxLot(
                    lot_id=f"{ticker}-{seq}",
                    ticker=ticker,
                    qty=row.qty,
                    cost=abs(row.amount),
                    acquired=day,
                )
            )
            continue
        sell_qty = abs(row.qty)
        if sell_qty <= 0:
            continue
        px = abs(row.amount / row.qty) if row.qty != 0 else Decimal("0")
        flat = [lot for lot in bucket if lot.qty > 0]
        rows = fifo_realize(flat, ticker=ticker, sell_qty=sell_qty, sale_price=px, sold_on=day)
        if day.year == year:
            realized.extend(rows)
        left = sell_qty
        kept: list[TaxLot] = []
        for lot in bucket:
            if left <= 0 or lot.ticker != ticker:
                kept.append(lot)
                continue
            if lot.qty <= left:
                left -= lot.qty
                continue
            remain = lot.qty - left
            cost = lot.cost * remain / lot.qty
            kept.append(TaxLot(lot.lot_id, lot.ticker, remain, cost, lot.acquired))
            left = Decimal("0")
        lots[ticker] = kept
    return realized


def explain_tax(
    user_id: str,
    *,
    mode: str = "paper",
    resident: bool = True,
    account_type: str | None = None,
    iis_opened_on: date | None = None,
    iis_contribution: Decimal | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    started = perf_counter()
    caption = CAPTION
    if filter_wording(caption):
        caption = NO_DATA
    if not is_enabled("qa_k3_tax"):
        return _empty("qa_k3_tax off", elapsed_ms=round((perf_counter() - started) * 1000.0, 3))
    # Demo-only until lawyer confirms: refuse live books.
    if mode != "paper":
        return _empty(
            "только демо (paper), пока методику не подтвердит юрист",
            elapsed_ms=round((perf_counter() - started) * 1000.0, 3),
        )
    day = as_of or date.today()
    open_lots = _open_lots(user_id, mode)
    marks = _marks(user_id, mode)
    if not open_lots and not marks:
        return _empty("нет позиций", elapsed_ms=round((perf_counter() - started) * 1000.0, 3))

    lth_rows = [
        position_lth_row(lot, mark_price=marks.get(lot.ticker), as_of=day, resident=resident)
        for lot in open_lots
    ]
    realized = _realized_year(user_id, mode, day.year)
    year_block = year_ndfl_estimate(realized, year=day.year, resident=resident)
    harvest = loss_harvest_rows(
        open_lots,
        marks=marks,
        realized_rows=realized,
        as_of=day,
        resident=resident,
    )
    iis = iis_block(
        account_type=account_type,
        opened_on=iis_opened_on,
        contribution=iis_contribution,
    )
    missing = [r["ticker"] for r in lth_rows if r.get("status") == NO_DATA]
    status = "ok" if lth_rows and not missing else ("частично" if lth_rows else NO_DATA)
    if missing and not lth_rows:
        status = NO_DATA
    out = {
        "data_status": status,
        "reason": "" if status == "ok" else ("нет цены: " + ", ".join(missing) if missing else "нет лотов"),
        "lth": lth_rows,
        "year": year_block,
        "loss_harvest": harvest,
        "iis": iis,
        "rates": rates_snapshot(),
        "methodology": METHOD,
        "lawyer_gate": LAWYER,
        "caption": caption,
        "demo_only": True,
        "mode": mode,
        "resident": resident,
        "as_of": day.isoformat(),
        "source": "данные портфеля",
        "rate": NDFL_RATE_LABEL,
        "elapsed_ms": round((perf_counter() - started) * 1000.0, 3),
        "missing": missing,
    }
    return out
