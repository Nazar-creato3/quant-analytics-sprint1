"""Single write/read API for portfolio positions (Prompt 05)."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.services.market_data.eod import EodRow, MissingOfficialClose, get_eod_price
from app.services.portfolio_book.store import (
    Account,
    BookModeError,
    BookPosition,
    Mode,
    get_book,
)
from app.services.qa.feature_flags import is_enabled


def ensure_account(
    *,
    account_id: str,
    user_id: str,
    venue: str,
    mode: Mode,
    source: str = "platform",
    status: str = "ok",
    history_depth_days: int = 0,
) -> Account:
    book = get_book()
    return book.upsert_account(
        Account(
            id=account_id,
            user_id=user_id,
            venue=venue,
            mode=mode,
            source=source,
            status=status,
            last_sync=datetime.now(timezone.utc),
            history_depth_days=history_depth_days,
        )
    )


def record_transaction(
    *,
    account_id: str,
    user_id: str,
    mode: Mode,
    venue: str,
    external_id: str,
    kind: str,
    instrument_id: str,
    ticker: str,
    qty: Decimal | str,
    amount: Decimal | str,
    ccy: str,
    event_time: datetime,
    recorded_at: datetime | None = None,
) -> Any:
    if not is_enabled("qa_portfolio_book"):
        return None
    return get_book().append_txn(
        {
            "account_id": account_id,
            "user_id": user_id,
            "mode": mode,
            "venue": venue,
            "external_id": external_id,
            "kind": kind,
            "instrument_id": instrument_id,
            "ticker": ticker,
            "qty": qty,
            "amount": amount,
            "ccy": ccy,
            "event_time": event_time,
            "recorded_at": recorded_at,
        }
    )


def record_bot_trade(
    *,
    user_id: str,
    ticker: str,
    qty: Decimal | str,
    amount: Decimal | str,
    ccy: str,
    side: str,
    external_id: str,
    event_time: datetime | None = None,
) -> Any:
    account_id = f"paper-bots:{user_id}"
    ensure_account(account_id=account_id, user_id=user_id, venue="bots", mode="paper", source="bot")
    signed = Decimal(str(qty))
    if str(side).lower() in {"sell", "short"}:
        signed = -abs(signed)
    else:
        signed = abs(signed)
    return record_transaction(
        account_id=account_id,
        user_id=user_id,
        mode="paper",
        venue="bots",
        external_id=external_id,
        kind="trade",
        instrument_id=ticker,
        ticker=ticker,
        qty=signed,
        amount=amount,
        ccy=ccy,
        event_time=event_time or datetime.now(timezone.utc),
    )


def positions_for(*, user_id: str, mode: Mode, as_of_event: datetime | None = None, as_of_recorded: datetime | None = None) -> list[BookPosition]:
    if not is_enabled("qa_portfolio_book"):
        return []
    return get_book().positions(user_id=user_id, mode=mode, as_of_event=as_of_event, as_of_recorded=as_of_recorded)


def value_positions(rows: list[BookPosition], eod: dict[str, EodRow]) -> list[dict[str, Any]]:
    from app.services.price_history import service as history

    need = [r.ticker for r in rows if r.ticker and r.ticker.upper() != "CASH" and r.ticker not in eod and r.instrument_id not in eod]
    if need:
        eod = {**history.eod_map(need), **eod}
        history.want([t for t in need if t.upper() not in eod])
    out: list[dict[str, Any]] = []
    for pos in rows:
        row = eod.get(pos.instrument_id) or eod.get(pos.ticker)
        if row is None:
            out.append(
                {
                    "ticker": pos.ticker,
                    "qty": str(pos.qty),
                    "ccy": pos.ccy,
                    "mode": pos.mode,
                    "account_id": pos.account_id,
                    "value": None,
                    "as_of": None,
                    "price_type": None,
                }
            )
            continue
        try:
            price, note = get_eod_price(row, purpose="valuation")
        except MissingOfficialClose:
            out.append(
                {
                    "ticker": pos.ticker,
                    "qty": str(pos.qty),
                    "ccy": pos.ccy,
                    "mode": pos.mode,
                    "account_id": pos.account_id,
                    "value": None,
                    "as_of": row.session_date.isoformat(),
                    "price_type": "missing_official_close",
                }
            )
            continue
        out.append(
            {
                "ticker": pos.ticker,
                "qty": str(pos.qty),
                "ccy": pos.ccy,
                "mode": pos.mode,
                "account_id": pos.account_id,
                "value": str(pos.qty * price),
                "price": str(price),
                "value_rub": (lambda v: None if v is None else str(round(v, 2)))(history.to_rub(float(pos.qty * price), pos.ccy)),
                "as_of": row.session_date.isoformat(),
                "price_type": note,
            }
        )
    return out


def assert_mode(requested: str) -> Mode:
    if requested not in {"paper", "live"}:
        raise BookModeError("mode must be paper or live")
    return requested  # type: ignore[return-value]


def record_transactions(rows: list[dict[str, Any]]) -> tuple[int, int]:
    """Bulk version of record_transaction for broker syncs. Returns (added, duplicates)."""
    if not is_enabled("qa_portfolio_book") or not rows:
        return 0, 0
    return get_book().append_txns(rows)
