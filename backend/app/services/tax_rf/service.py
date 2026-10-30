"""K3 tax demo payload. Numbers from target_portfolio.tax only.

docs/methodology/tax.md. Flag qa_tax_rf defaults off ([ЮРИСТ]).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.qa.feature_flags import is_enabled
from app.services.target_portfolio.tax import (
    CITATION_214,
    CITATION_219,
    LTH_YEARS,
    NDFL_RATE_LABEL,
    fifo_realize,
    full_years,
    iis_note,
    ndfl_cash,
    tax_base_for_year,
)
from app.services.target_portfolio.types import TaxLot
from app.services.tax_rf import demo as fixtures

METHOD = "/methodology/tax"
FLAG = "qa_tax_rf"


def lth_unlock_date(acquired: date) -> date:
    """First calendar day when holding reaches LTH_YEARS full years (ст. 219.1 / OQ-36-1)."""
    try:
        return acquired.replace(year=acquired.year + LTH_YEARS)
    except ValueError:
        # 29 Feb → 28 Feb in non-leap unlock year
        return acquired.replace(year=acquired.year + LTH_YEARS, day=28)


def _sell_today_row(lot: TaxLot, mark_total: Decimal, as_of: date) -> dict[str, object]:
    sale_price = (mark_total / lot.qty) if lot.qty else Decimal("0")
    rows = fifo_realize(
        [lot],
        ticker=lot.ticker,
        sell_qty=lot.qty,
        sale_price=sale_price,
        sold_on=as_of,
    )
    row = rows[0] if rows else {}
    unlock = lth_unlock_date(lot.acquired)
    years_now = full_years(lot.acquired, as_of)
    eligible_now = years_now >= LTH_YEARS
    # Tax if sold today (single-lot year slice) vs after unlock (same marks, unlock date).
    today_base = tax_base_for_year(rows, as_of.year, resident=True) if rows else {}
    after_rows = fifo_realize(
        [lot],
        ticker=lot.ticker,
        sell_qty=lot.qty,
        sale_price=sale_price,
        sold_on=max(unlock, as_of),
    )
    after_base = (
        tax_base_for_year(after_rows, max(unlock, as_of).year, resident=True) if after_rows else {}
    )
    return {
        "ticker": lot.ticker,
        "lot_id": lot.lot_id,
        "acquired": lot.acquired.isoformat(),
        "lth_unlock_on": unlock.isoformat(),
        "full_years_today": years_now,
        "lth_eligible_today": eligible_now,
        "unrealized_result": row.get("result"),
        "tax_if_sell_today": today_base.get("tax_cash"),
        "tax_base_if_sell_today": today_base.get("tax_base"),
        "tax_if_sell_after_lth": after_base.get("tax_cash"),
        "tax_base_if_sell_after_lth": after_base.get("tax_base"),
        "citation_219": CITATION_219,
    }


def _harvest_estimate(
    ytd_rows: list[dict[str, str]],
    open_lots: list[TaxLot],
    marks: dict[str, Decimal],
    *,
    year: int,
    as_of: date,
) -> dict[str, str | None]:
    """How much NDFL cash falls if all open unrealized losses are realized by year-end."""
    before = tax_base_for_year(ytd_rows, year, resident=True)
    harvest_rows = list(ytd_rows)
    for lot in open_lots:
        mark = marks.get(lot.ticker)
        if mark is None:
            continue
        sale_price = mark / lot.qty
        realized = fifo_realize(
            [lot],
            ticker=lot.ticker,
            sell_qty=lot.qty,
            sale_price=sale_price,
            sold_on=as_of,
        )
        if not realized:
            continue
        if Decimal(realized[0]["result"]) >= 0:
            continue
        harvest_rows.extend(realized)
    after = tax_base_for_year(harvest_rows, year, resident=True)
    before_cash = Decimal(str(before["tax_cash"] or "0"))
    after_cash = Decimal(str(after["tax_cash"] or "0"))
    saving = before_cash - after_cash
    if saving < 0:
        saving = Decimal("0")
    return {
        "ytd_tax_cash": before.get("tax_cash"),  # type: ignore[return-value]
        "ytd_tax_base": before.get("tax_base"),  # type: ignore[return-value]
        "after_harvest_tax_cash": after.get("tax_cash"),  # type: ignore[return-value]
        "tax_cash_reduction": format(saving, "f"),
        "note": "оценка по открытым позициям",
        "rate": NDFL_RATE_LABEL,
        "citation_214": CITATION_214,
    }


def _mark_totals(user_id: str, mode: str = "paper") -> dict[str, Decimal]:
    from app.services.concentration.service import _trade_price
    from app.services.portfolio_book.store import get_book

    out: dict[str, Decimal] = {}
    for pos in get_book().positions(user_id=user_id, mode=mode):  # type: ignore[arg-type]
        ticker = (pos.ticker or "").upper()
        if not ticker or ticker == "CASH":
            continue
        px = _trade_price(user_id, mode, ticker)
        if px is None:
            continue
        out[ticker] = abs(pos.qty) * Decimal(str(px))
    return out


def _payload_from_book(
    user_id: str,
    *,
    as_of: date,
    resident: bool,
    open_lots: list[TaxLot],
    marks: dict[str, Decimal],
    realized_ytd: list[dict[str, str]],
    iis: dict[str, object],
    status: str,
    source: str,
) -> dict:
    year = as_of.year
    ytd = tax_base_for_year(realized_ytd, year, resident=resident)
    positions = [
        _sell_today_row(lot, marks[lot.ticker], as_of)
        for lot in open_lots
        if lot.ticker in marks
    ]
    harvest = _harvest_estimate(
        realized_ytd,
        open_lots,
        marks,
        year=year,
        as_of=as_of,
    )
    if iis.get("applied") and resident and iis.get("deduction_base"):
        iis = {
            **iis,
            "tax_cash": format(
                ndfl_cash(Decimal(str(iis["deduction_base"])), resident=True, income="securities"),
                "f",
            ),
            "tax_cash_reason": "оценка вычета типа А по взносу",
        }
    return {
        "status": status,
        "flag": FLAG,
        "lawyer_gate": "[ЮРИСТ]",
        "user_id": user_id,
        "as_of": as_of.isoformat(),
        "year": str(year),
        "resident": resident,
        "ytd": ytd,
        "positions": positions,
        "harvest": harvest,
        "iis": iis,
        "methodology": METHOD,
        "source": source,
        "rate": NDFL_RATE_LABEL,
        "data_status": "ok",
        "texts_key": "tax",
    }


def fixture_tax_payload(
    user_id: str = "fixture",
    *,
    as_of: date | None = None,
    resident: bool = True,
) -> dict:
    """Golden-lot payload for methodology checks. Not the user-facing path."""
    as_of = as_of or fixtures.DEMO_AS_OF
    iis = iis_note(
        account_type=str(fixtures.DEMO_IIS["account_type"]),
        opened_on=fixtures.DEMO_IIS["opened_on"],  # type: ignore[arg-type]
        contribution=fixtures.DEMO_IIS["contribution"],  # type: ignore[arg-type]
    )
    return _payload_from_book(
        user_id,
        as_of=as_of,
        resident=resident,
        open_lots=fixtures.OPEN_LOTS,
        marks=fixtures.MARKS,
        realized_ytd=fixtures.REALIZED_YTD,
        iis=iis,
        status="demo",
        source="demo_fixture",
    )


def demo_tax_payload(
    user_id: str,
    *,
    as_of: date | None = None,
    resident: bool = True,
) -> dict:
    """RF tax view from the user book when qa_tax_rf is on."""
    if not is_enabled(FLAG, user_id=user_id):
        return {
            "status": "flag_off",
            "flag": FLAG,
            "lawyer_gate": "[ЮРИСТ]",
            "methodology": METHOD,
            "message_key": "tax.flag_off",
        }
    from app.services.tax_ru.service import _open_lots, _realized_year

    as_of = as_of or date.today()
    open_lots = _open_lots(user_id, "paper")
    marks = _mark_totals(user_id, "paper")
    realized_ytd = _realized_year(user_id, "paper", as_of.year)
    if not open_lots and not realized_ytd:
        return {
            "status": "нет данных",
            "flag": FLAG,
            "lawyer_gate": "[ЮРИСТ]",
            "methodology": METHOD,
            "user_id": user_id,
            "as_of": as_of.isoformat(),
            "data_status": "нет данных",
            "positions": [],
            "ytd": None,
            "harvest": None,
            "iis": {"applied": False, "reason": "нет данных"},
            "texts_key": "tax",
        }
    iis = iis_note(account_type="broker", opened_on=None, contribution=None)
    return _payload_from_book(
        user_id,
        as_of=as_of,
        resident=resident,
        open_lots=open_lots,
        marks=marks,
        realized_ytd=realized_ytd,
        iis=iis,
        status="ok",
        source="portfolio_book",
    )
