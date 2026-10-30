"""Securities tax base and NDFL cash.

Check date 2026-10-06. Articles of the Tax Code of the Russian Federation:
224 (rates), 214.1 (FIFO and within-year netting), 219.1 (long-term holding).
The founder supplied the figures on 2026-10-07 (OQ-36-1). No other brackets,
fees, or thresholds are applied.

Resident, securities-operations income and dividends: 13% up to 2 400 000 RUB
per year, 15% on the excess.
Non-resident: 30% on securities operations, 15% on dividends.
Long-term holding relief: exempt profit up to 3 000 000 RUB for each full year
of holding, only when holding is at least 3 full years.
Profit and loss are netted inside the year.

Article 214.1 (https://www.consultant.ru/document/cons_doc_LAW_28165/d5ddddc549f21e5c4a826cda7cb4efd57a1cff46/):
«При реализации ценных бумаг расходы в виде стоимости приобретения ценных
бумаг признаются по стоимости первых по времени приобретений (ФИФО).»
«Отрицательный финансовый результат, полученный в налоговом периоде по
отдельным операциям с ценными бумагами … уменьшает финансовый результат,
полученный в налоговом периоде по совокупности соответствующих операций.»

Article 219.1 (https://www.consultant.ru/document/cons_doc_LAW_28165/2b69106f66601ba5b58aaeb82395674581c66c20/):
the cap for one common holding period is K_cb × 3 000 000 rubles. The cash
relief here follows the founder figure: 3 000 000 RUB per full year, and only
when the holding is at least 3 full years. IIS cash after 31.12.2023 is not
computed (OQ-36-3). Different full-year counts in one year are not folded into
one K_cb (OQ-36-2).
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

from app.services.target_portfolio.types import TaxLot

LTH_YEARS = 3
LTH_CAP_PER_YEAR = Decimal("3000000")
IIS_COMBINED_CAP = Decimal("400000")
MONEY = Decimal("0.01")
# Founder figures, supplied 2026-10-07. Source check date 2026-10-06.
RESIDENT_BRACKET_RUB = Decimal("2400000")
RESIDENT_RATE_UP_TO_BRACKET = Decimal("0.13")
RESIDENT_RATE_ABOVE_BRACKET = Decimal("0.15")
NONRESIDENT_SECURITIES_RATE = Decimal("0.30")
NONRESIDENT_DIVIDEND_RATE = Decimal("0.15")
NDFL_RATE_LABEL = (
    "резидент: операции и дивиденды 13% до 2400000 RUB в год, далее 15%; "
    "нерезидент: операции 30%, дивиденды 15%"
)
REASON_NO_RESIDENCY = (
    "ставка НДФЛ ст. 224 НК РФ сверена 2026-10-06, но резидентство лица не задано, "
    "денежный налог не начисляется"
)

CITATION_214 = (
    "НК РФ ст. 214.1 (117-ФЗ, ред. 04.08.2026, текст КонсультантПлюс): ФИФО; "
    "отрицательный результат налогового периода уменьшает результат совокупности операций"
)
CITATION_219 = (
    "НК РФ ст. 219.1 (117-ФЗ, ред. 04.08.2026, текст КонсультантПлюс): "
    "вычет при владении более трёх лет, предел Кцб × 3 000 000 руб.; "
    "ИИС, открытый до 31.12.2023 включительно"
)


def full_years(acquired: date, sold: date) -> int:
    years = sold.year - acquired.year
    if (sold.month, sold.day) < (acquired.month, acquired.day):
        years -= 1
    return max(0, years)


def held_more_than_three_years(acquired: date, sold: date) -> bool:
    """At least three full years (founder rule, 2026-10-07)."""
    return full_years(acquired, sold) >= LTH_YEARS


def ndfl_cash(taxable: Decimal, *, resident: bool, income: str) -> Decimal:
    """Cash NDFL. income is 'securities' or 'dividends'. No other kinds."""
    if income not in {"securities", "dividends"}:
        raise ValueError("income")
    base = taxable if taxable > 0 else Decimal("0")
    if resident:
        if base <= RESIDENT_BRACKET_RUB:
            tax = base * RESIDENT_RATE_UP_TO_BRACKET
        else:
            excess = base - RESIDENT_BRACKET_RUB
            tax = RESIDENT_BRACKET_RUB * RESIDENT_RATE_UP_TO_BRACKET
            tax += excess * RESIDENT_RATE_ABOVE_BRACKET
    elif income == "securities":
        tax = base * NONRESIDENT_SECURITIES_RATE
    else:
        tax = base * NONRESIDENT_DIVIDEND_RATE
    return tax.quantize(MONEY, rounding=ROUND_HALF_EVEN)


def dividend_ndfl(amount: Decimal, *, resident: bool | None) -> dict[str, str | None]:
    """Dividend cash from the same scale. None until residency is known."""
    base = amount if amount > 0 else Decimal("0")
    base = base.quantize(MONEY, rounding=ROUND_HALF_EVEN)
    if resident is None:
        return {
            "tax_base": format(base, "f"),
            "tax_cash": None,
            "tax_cash_reason": REASON_NO_RESIDENCY,
            "rate": NDFL_RATE_LABEL,
        }
    cash = ndfl_cash(base, resident=resident, income="dividends")
    return {
        "tax_base": format(base, "f"),
        "tax_cash": format(cash, "f"),
        "tax_cash_reason": "",
        "rate": NDFL_RATE_LABEL,
    }


def fifo_realize(
    lots: list[TaxLot],
    *,
    ticker: str,
    sell_qty: Decimal,
    sale_price: Decimal,
    sold_on: date,
) -> list[dict[str, str]]:
    """Oldest lots first. Returns per-lot money results; does not invent a tax rate."""
    if sell_qty <= 0:
        return []
    matched = [lot for lot in lots if lot.ticker == ticker and lot.qty > 0]
    ordered = sorted(matched, key=lambda lot: (lot.acquired, lot.lot_id))
    left = sell_qty
    rows: list[dict[str, str]] = []
    for lot in ordered:
        if left <= 0:
            break
        take = lot.qty if lot.qty <= left else left
        cost = (lot.cost * take / lot.qty).quantize(MONEY, rounding=ROUND_HALF_EVEN)
        proceeds = (sale_price * take).quantize(MONEY, rounding=ROUND_HALF_EVEN)
        result = proceeds - cost
        rows.append(
            {
                "lot_id": lot.lot_id,
                "ticker": ticker,
                "qty": format(take, "f"),
                "proceeds": format(proceeds, "f"),
                "cost": format(cost, "f"),
                "result": format(result, "f"),
                "acquired": lot.acquired.isoformat(),
                "sold_on": sold_on.isoformat(),
                "year": str(sold_on.year),
                "full_years": str(full_years(lot.acquired, sold_on)),
                "long_term": "true" if held_more_than_three_years(lot.acquired, sold_on) else "false",
            }
        )
        left -= take
    return rows


def tax_base_for_year(
    rows: list[dict[str, str]],
    year: int,
    *,
    resident: bool | None = None,
) -> dict[str, str | bool | None]:
    """Within-year net, then the long-term deduction when every eligible lot shares K."""
    chosen = [row for row in rows if int(row["year"]) == year]
    net = sum((Decimal(row["result"]) for row in chosen), Decimal("0"))
    eligible = [row for row in chosen if row["long_term"] == "true" and Decimal(row["result"]) > 0]
    relief = Decimal("0")
    relief_applied = False
    relief_reason = "нет лотов со сроком владения более трёх лет"
    if eligible:
        years = {int(row["full_years"]) for row in eligible}
        if len(years) != 1:
            relief_reason = "коэффициент Кцб для разных сроков владения не считается (OQ-36-2)"
        else:
            k = years.pop()
            eligible_gain = sum((Decimal(row["result"]) for row in eligible), Decimal("0"))
            cap = LTH_CAP_PER_YEAR * Decimal(k)
            relief = eligible_gain if eligible_gain < cap else cap
            if net <= 0:
                relief = Decimal("0")
                relief_reason = "налоговая база до вычета не положительна"
            else:
                if relief > net:
                    relief = net
                relief_applied = True
                relief_reason = ""
    base = net - relief
    if base < 0:
        base = Decimal("0")
    base = base.quantize(MONEY, rounding=ROUND_HALF_EVEN)
    relief = relief.quantize(MONEY, rounding=ROUND_HALF_EVEN)
    if resident is None:
        cash: str | None = None
        cash_reason = REASON_NO_RESIDENCY
    else:
        cash = format(ndfl_cash(base, resident=resident, income="securities"), "f")
        cash_reason = ""
    return {
        "year": str(year),
        "net_before_relief": format(net.quantize(MONEY, rounding=ROUND_HALF_EVEN), "f"),
        "relief": format(relief, "f"),
        "relief_applied": relief_applied,
        "relief_reason": relief_reason,
        "tax_base": format(base, "f"),
        "tax_cash": cash,
        "tax_cash_reason": cash_reason,
        "rate": NDFL_RATE_LABEL,
        "resident": None if resident is None else resident,
        "citation_214": CITATION_214,
        "citation_219": CITATION_219,
        "citation_224": "НК РФ ст. 224, сверка 2026-10-06, цифры основателя 2026-10-07",
    }


def iis_note(
    *,
    account_type: str,
    opened_on: date | None,
    contribution: Decimal | None,
) -> dict[str, str | bool | None]:
    kind = (account_type or "").lower()
    if not kind.startswith("iis"):
        return {"applied": False, "reason": "счёт не ИИС", "deduction_base": None, "tax_cash": None}
    if opened_on is None:
        return {
            "applied": False,
            "reason": "дата открытия ИИС не задана",
            "deduction_base": None,
            "tax_cash": None,
        }
    if opened_on > date(2023, 12, 31):
        return {
            "applied": False,
            "reason": "ИИС, открытый после 31.12.2023, не сверен (OQ-36-3)",
            "deduction_base": None,
            "tax_cash": None,
        }
    if contribution is None:
        return {
            "applied": False,
            "reason": "сумма взноса на ИИС не задана",
            "deduction_base": None,
            "tax_cash": None,
        }
    base = contribution if contribution < IIS_COMBINED_CAP else IIS_COMBINED_CAP
    if base < 0:
        base = Decimal("0")
    return {
        "applied": True,
        "reason": "",
        "deduction_base": format(base.quantize(MONEY, rounding=ROUND_HALF_EVEN), "f"),
        "tax_cash": None,
        "tax_cash_reason": "ставка НДФЛ не сверена, вычет ИИС в деньгах не считается",
        "citation_219": CITATION_219,
    }
