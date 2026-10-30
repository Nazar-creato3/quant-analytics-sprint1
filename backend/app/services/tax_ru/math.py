"""Pure tax math for K3 screens. Numbers from target_portfolio.tax only.

Methodology: docs/methodology/tax.md (R6; [ЮРИСТ] until lawyer confirms).
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from app.services.target_portfolio.tax import (
    LTH_YEARS,
    MONEY,
    NDFL_RATE_LABEL,
    RESIDENT_BRACKET_RUB,
    fifo_realize,
    full_years,
    held_more_than_three_years,
    iis_note,
    ndfl_cash,
    tax_base_for_year,
)
from app.services.target_portfolio.types import TaxLot

NO_DATA = "нет данных"


def lth_free_from(acquired: date) -> date:
    """First calendar day when holding reaches three full years."""
    try:
        return acquired.replace(year=acquired.year + LTH_YEARS)
    except ValueError:
        # 29 Feb → 28 Feb in non-leap target year
        return acquired.replace(year=acquired.year + LTH_YEARS, day=28)


def position_lth_row(
    lot: TaxLot,
    *,
    mark_price: Decimal | None,
    as_of: date,
    resident: bool = True,
) -> dict[str, Any]:
    """LTH date and tax if sold today vs on/after LTH date."""
    free_from = lth_free_from(lot.acquired)
    years_now = full_years(lot.acquired, as_of)
    if mark_price is None:
        return {
            "ticker": lot.ticker,
            "lot_id": lot.lot_id,
            "qty": format(lot.qty, "f"),
            "acquired": lot.acquired.isoformat(),
            "lth_free_from": free_from.isoformat(),
            "full_years_now": years_now,
            "eligible_now": held_more_than_three_years(lot.acquired, as_of),
            "tax_if_sell_today": None,
            "tax_if_sell_after_lth": None,
            "paper_result": None,
            "status": NO_DATA,
            "reason": "нет цены",
        }
    today_rows = fifo_realize(
        [lot],
        ticker=lot.ticker,
        sell_qty=lot.qty,
        sale_price=mark_price,
        sold_on=as_of,
    )
    after_rows = fifo_realize(
        [lot],
        ticker=lot.ticker,
        sell_qty=lot.qty,
        sale_price=mark_price,
        sold_on=free_from,
    )
    today_base = tax_base_for_year(today_rows, as_of.year, resident=resident)
    after_base = tax_base_for_year(after_rows, free_from.year, resident=resident)
    paper = Decimal(today_rows[0]["result"]) if today_rows else Decimal("0")
    return {
        "ticker": lot.ticker,
        "lot_id": lot.lot_id,
        "qty": format(lot.qty, "f"),
        "acquired": lot.acquired.isoformat(),
        "lth_free_from": free_from.isoformat(),
        "full_years_now": years_now,
        "eligible_now": held_more_than_three_years(lot.acquired, as_of),
        "tax_if_sell_today": today_base.get("tax_cash"),
        "tax_if_sell_after_lth": after_base.get("tax_cash"),
        "tax_base_today": today_base.get("tax_base"),
        "tax_base_after_lth": after_base.get("tax_base"),
        "relief_today": today_base.get("relief"),
        "relief_after_lth": after_base.get("relief"),
        "paper_result": format(paper.quantize(MONEY, rounding=ROUND_HALF_EVEN), "f"),
        "mark_price": format(mark_price.quantize(MONEY, rounding=ROUND_HALF_EVEN), "f"),
        "status": "ok",
        "rate": NDFL_RATE_LABEL,
    }


def year_ndfl_estimate(
    realized_rows: list[dict[str, str]],
    *,
    year: int,
    resident: bool = True,
) -> dict[str, Any]:
    """YTD NDFL from realized FIFO rows (13%/15% bracket)."""
    if not realized_rows:
        return {
            "year": str(year),
            "status": NO_DATA,
            "reason": "нет реализованных сделок за год",
            "tax_cash": None,
            "tax_base": None,
            "net_before_relief": None,
            "bracket_rub": str(RESIDENT_BRACKET_RUB),
            "rate": NDFL_RATE_LABEL,
        }
    block = tax_base_for_year(realized_rows, year, resident=resident)
    ytd = Decimal(str(block.get("tax_base") or "0"))
    return {
        "year": str(year),
        "status": "ok",
        "reason": "",
        "tax_cash": block.get("tax_cash"),
        "tax_base": block.get("tax_base"),
        "net_before_relief": block.get("net_before_relief"),
        "tax_on_next_1": format(
            marginal_tax_on_gain(Decimal("1"), ytd_base=ytd, resident=resident), "f"
        ),
        "relief": block.get("relief"),
        "relief_applied": block.get("relief_applied"),
        "bracket_rub": str(RESIDENT_BRACKET_RUB),
        "rate": NDFL_RATE_LABEL,
        "citation_214": block.get("citation_214"),
        "citation_224": block.get("citation_224"),
    }


def loss_harvest_rows(
    open_lots: list[TaxLot],
    *,
    marks: dict[str, Decimal],
    realized_rows: list[dict[str, str]],
    as_of: date,
    resident: bool = True,
) -> list[dict[str, Any]]:
    """For each open lot with paper loss: tax reduction if realized before year-end."""
    year = as_of.year
    baseline = tax_base_for_year(realized_rows, year, resident=resident)
    base_cash = Decimal(str(baseline["tax_cash"] or "0"))
    out: list[dict[str, Any]] = []
    for lot in open_lots:
        px = marks.get(lot.ticker)
        if px is None:
            out.append(
                {
                    "ticker": lot.ticker,
                    "lot_id": lot.lot_id,
                    "paper_result": None,
                    "tax_reduction": None,
                    "status": NO_DATA,
                    "reason": "нет цены",
                }
            )
            continue
        rows = fifo_realize(
            [lot],
            ticker=lot.ticker,
            sell_qty=lot.qty,
            sale_price=px,
            sold_on=as_of,
        )
        if not rows:
            continue
        paper = Decimal(rows[0]["result"])
        if paper >= 0:
            continue
        combined = tax_base_for_year(realized_rows + rows, year, resident=resident)
        new_cash = Decimal(str(combined["tax_cash"] or "0"))
        reduction = (base_cash - new_cash).quantize(MONEY, rounding=ROUND_HALF_EVEN)
        out.append(
            {
                "ticker": lot.ticker,
                "lot_id": lot.lot_id,
                "qty": format(lot.qty, "f"),
                "paper_result": format(paper.quantize(MONEY, rounding=ROUND_HALF_EVEN), "f"),
                "tax_cash_before": format(base_cash, "f"),
                "tax_cash_after": format(new_cash, "f"),
                "tax_reduction": format(reduction, "f"),
                "status": "ok",
                "note": "фиксация убытка меняет срок владения для ЛДВ при повторной покупке",
                "decision": "расчёт по позициям, решение за вами",
            }
        )
    return out


def iis_block(
    *,
    account_type: str | None,
    opened_on: date | None,
    contribution: Decimal | None,
) -> dict[str, Any]:
    if not account_type:
        return {
            "applied": False,
            "status": NO_DATA,
            "reason": "тип счёта брокер не отдал",
            "deduction_base": None,
            "tax_cash": None,
        }
    note = iis_note(account_type=account_type, opened_on=opened_on, contribution=contribution)
    return {
        **note,
        "status": "ok" if note.get("applied") else NO_DATA if "не сверен" in str(note.get("reason") or "") else "ok",
        "account_type": account_type,
        "opened_on": None if opened_on is None else opened_on.isoformat(),
    }


def marginal_tax_on_gain(gain: Decimal, *, ytd_base: Decimal, resident: bool = True) -> Decimal:
    """Extra NDFL if ``gain`` is added to YTD taxable base (resident securities)."""
    if not resident or gain <= 0:
        return Decimal("0.00")
    before = ndfl_cash(ytd_base if ytd_base > 0 else Decimal("0"), resident=True, income="securities")
    after = ndfl_cash(
        (ytd_base if ytd_base > 0 else Decimal("0")) + gain,
        resident=True,
        income="securities",
    )
    return (after - before).quantize(MONEY, rounding=ROUND_HALF_EVEN)
