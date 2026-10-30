"""Replay investor cash flows into an index or money-market sleeve (K1 / R7)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Sequence

from app.services.quant_math.book import money_weighted_return, time_weighted_return

KOPECK = Decimal("0.01")


def last_price_on_or_before(prices: Sequence[tuple[date, Decimal]], as_of: date) -> Decimal | None:
    chosen: Decimal | None = None
    for day, price in sorted(prices, key=lambda row: row[0]):
        if day <= as_of:
            chosen = price
    return chosen


def replay_index_cashflows(
    cashflows: Sequence[tuple[date, Decimal]],
    prices: Sequence[tuple[date, Decimal]],
    as_of: date,
) -> dict[str, Decimal | str | None]:
    """Same dates and amounts as the book: buy on deposit, sell on withdrawal."""
    units = Decimal("0")
    pairs: list[tuple[Decimal, Decimal]] = []
    start_after: Decimal | None = None
    event_days = sorted({day for day, _ in cashflows} | {as_of})
    cf_by_day: dict[date, Decimal] = {}
    for day, amount in cashflows:
        cf_by_day[day] = cf_by_day.get(day, Decimal("0")) + amount

    for day in event_days:
        px = last_price_on_or_before(prices, day)
        if px is None or px <= 0:
            return {
                "data_status": "нет данных",
                "reason": f"нет цены на {day.isoformat()}",
                "end_value": None,
                "twr": None,
                "mwr": None,
            }
        if units > 0 and start_after is not None:
            pairs.append((start_after, units * px))
        flow = cf_by_day.get(day, Decimal("0"))
        if flow > 0:
            units += flow / px
        elif flow < 0:
            sell = abs(flow) / px
            if sell > units:
                return {
                    "data_status": "нет данных",
                    "reason": f"вывод больше стоимости альтернативы на {day.isoformat()}",
                    "end_value": None,
                    "twr": None,
                    "mwr": None,
                }
            units -= sell
        start_after = units * px

    end_px = last_price_on_or_before(prices, as_of)
    if end_px is None:
        return {
            "data_status": "нет данных",
            "reason": "нет конечной цены",
            "end_value": None,
            "twr": None,
            "mwr": None,
        }
    end_value = (units * end_px).quantize(KOPECK, rounding=ROUND_HALF_EVEN)
    twr = time_weighted_return(pairs) if pairs else Decimal("0")
    mwr_flows = [(day, -amount) for day, amount in cashflows] + [(as_of, end_value)]
    try:
        mwr = money_weighted_return(mwr_flows)
    except Exception:
        mwr = None
    return {
        "data_status": "ok" if mwr is not None else "недостаточно данных",
        "reason": None if mwr is not None else "MWR не посчитан",
        "end_value": end_value,
        "twr": twr,
        "mwr": mwr,
        "units": units,
    }
