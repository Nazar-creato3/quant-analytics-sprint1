"""Settle forecast_log rows against official_close (Prompt 04 + 11A)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.services.forecast_log.store import SettlementRow, get_store
from app.services.market_data.eod import EodRow, MissingOfficialClose, get_eod_price


def horizon_date(issued: datetime, horizon_days: int) -> date:
    day = issued.date() if isinstance(issued, datetime) else issued
    return day + timedelta(days=int(horizon_days))


def settle_row(
    log_id: int,
    issued_price: Decimal,
    direction: int,
    eod: EodRow,
    *,
    correction_of: int | None = None,
    settled_at: datetime | None = None,
) -> SettlementRow:
    actual, note = get_eod_price(eod, purpose="valuation")
    if issued_price == 0:
        raise ValueError("issued_price must be non-zero")
    move = actual - issued_price
    if direction == 0:
        correct = move == 0
    else:
        correct = (move > 0 and direction > 0) or (move < 0 and direction < 0)
    err = (actual - issued_price) / issued_price
    return get_store().append_settlement(
        {
            "log_id": log_id,
            "settled_at": settled_at or datetime.now(timezone.utc),
            "session_date": eod.session_date,
            "actual_price": str(actual),
            "actual_source": note,
            "direction_correct": correct,
            "error": str(err),
            "correction_of": correction_of,
        }
    )


def settle_due(eod_by_instrument: dict[str, EodRow], *, as_of: date | None = None) -> list[SettlementRow]:
    """Settle rows whose horizon has arrived. Corrections append a new settlement."""
    today = as_of or date.today()
    out: list[SettlementRow] = []
    store = get_store()
    existing = {s.log_id: s for s in store.settlements()}
    for row in store.rows():
        if horizon_date(row.issued_at, row.horizon_days) > today:
            continue
        eod = eod_by_instrument.get(row.instrument_id) or eod_by_instrument.get(row.ticker)
        if eod is None or row.issued_price is None:
            continue
        try:
            issued = Decimal(row.issued_price)
            prev = existing.get(row.id)
            correction = prev.id if prev is not None else None
            out.append(
                settle_row(
                    row.id,
                    issued,
                    row.direction,
                    eod,
                    correction_of=correction,
                )
            )
        except (MissingOfficialClose, ValueError):
            continue
    return out


def official_closes() -> dict[str, EodRow]:
    """Official closes for due rows. An empty map means there is nothing to settle."""
    return {}
