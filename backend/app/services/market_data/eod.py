"""Official close vs last trade (Prompt 04)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

Purpose = Literal["valuation", "intraday", "display"]


@dataclass(frozen=True)
class EodRow:
    instrument_id: str
    session_date: date
    official_close: Decimal | None
    last_close: Decimal | None
    volume: Decimal | None
    source: str
    board: str | None
    license_tag: str
    as_of: date


class MissingOfficialClose(Exception):
    def __init__(self, instrument_id: str, session_date: date) -> None:
        super().__init__(f"no official close for {instrument_id} on {session_date}")
        self.instrument_id = instrument_id
        self.session_date = session_date


def get_eod_price(row: EodRow, *, purpose: Purpose) -> tuple[Decimal, str]:
    """Return (price, note). Valuation never substitutes last for official."""
    if purpose == "valuation":
        if row.official_close is None:
            raise MissingOfficialClose(row.instrument_id, row.session_date)
        return row.official_close, "official_close"
    if purpose == "display":
        if row.official_close is not None:
            return row.official_close, "official_close"
        if row.last_close is None:
            raise MissingOfficialClose(row.instrument_id, row.session_date)
        return row.last_close, "last_available_not_traded"
    if row.last_close is not None:
        return row.last_close, "last_close"
    if row.official_close is not None:
        return row.official_close, "official_close"
    raise MissingOfficialClose(row.instrument_id, row.session_date)
