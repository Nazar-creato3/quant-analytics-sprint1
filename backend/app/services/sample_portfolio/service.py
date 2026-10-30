"""A realistic sample book in the user's paper portfolio.

Real, liquid instruments a Russian retail investor typically holds, so every
analytics block (risk, stress, factors, key rate, payouts, taxes, costs,
liquidity) computes on live market prices. The sample lives in its own paper
account ``sample:<user>`` and is removed in one call; it never touches a
connected broker account.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.services.portfolio_book.service import ensure_account, record_transaction
from app.services.portfolio_book.store import get_book

SAMPLE_VENUE = "sample"

# ticker, qty, approx. cost (in ccy), ccy, bought N days ago
_ROWS: tuple[tuple[str, str, str, str, int], ...] = (
    ("SBER", "300", "90000", "RUB", 420),
    ("LKOH", "12", "84000", "RUB", 400),
    ("GAZP", "400", "56000", "RUB", 380),
    ("YDEX", "15", "60000", "RUB", 300),
    ("MOEX", "300", "60000", "RUB", 250),
    ("LQDT", "40000", "70000", "RUB", 200),
    ("SU26238RMFS4", "60", "36000", "RUB", 330),
    ("ROSN", "60", "27000", "RUB", 360),
    ("PLZL", "2", "28000", "RUB", 280),
)
# RUB only: risk, key-rate and what-if engines value the book in roubles and
# skip a portfolio that mixes currencies, so a USD line would blank them out.


def sample_tickers() -> list[str]:
    return [r[0] for r in _ROWS]


def _account_id(user_id: str) -> str:
    return f"{SAMPLE_VENUE}:{user_id}"


def sample_state(user_id: str) -> dict[str, Any]:
    book = get_book()
    accounts = book.accounts_for(user_id=user_id)
    sample = any(a.id == _account_id(user_id) for a in accounts)
    real = [a for a in accounts if a.venue != SAMPLE_VENUE]
    paper_rows = book.positions(user_id=user_id, mode="paper")
    live_rows = book.positions(user_id=user_id, mode="live")
    own = [p for p in paper_rows + live_rows if not p.account_id.startswith(f"{SAMPLE_VENUE}:")]
    return {
        "sample_loaded": sample,
        "has_own_positions": bool(own),
        "has_positions": bool(paper_rows or live_rows),
        "accounts": [{"id": a.id, "venue": a.venue, "mode": a.mode} for a in real],
    }


def load_sample(user_id: str) -> dict[str, Any]:
    account_id = _account_id(user_id)
    ensure_account(account_id=account_id, user_id=user_id, venue=SAMPLE_VENUE, mode="paper", source="sample")
    now = datetime.now(timezone.utc)
    deposit_rub = sum(Decimal(r[2]) for r in _ROWS if r[3] == "RUB")
    start = now - timedelta(days=max(r[4] for r in _ROWS) + 1)
    for ccy, amount in (("RUB", deposit_rub),):
        record_transaction(
            account_id=account_id,
            user_id=user_id,
            mode="paper",
            venue=SAMPLE_VENUE,
            external_id=f"{account_id}:deposit:{ccy}",
            kind="deposit",
            instrument_id="CASH",
            ticker="CASH",
            qty="0",
            amount=str(amount),
            ccy=ccy,
            event_time=start,
        )
    for ticker, qty, cost, ccy, days in _ROWS:
        record_transaction(
            account_id=account_id,
            user_id=user_id,
            mode="paper",
            venue=SAMPLE_VENUE,
            external_id=f"{account_id}:{ticker}",
            kind="trade",
            instrument_id=ticker,
            ticker=ticker,
            qty=qty,
            amount=cost,  # same sign convention as the e2e demo book (cost as a positive amount)
            ccy=ccy,
            event_time=now - timedelta(days=days),
        )
        # Broker commission 0.05 % so the costs block has something real to show.
        record_transaction(
            account_id=account_id,
            user_id=user_id,
            mode="paper",
            venue=SAMPLE_VENUE,
            external_id=f"{account_id}:{ticker}:fee",
            kind="fee",
            instrument_id=ticker,
            ticker=ticker,
            qty="0",
            amount=str((Decimal(cost) * Decimal("0.0005")).quantize(Decimal("0.01"))),
            ccy=ccy,
            event_time=now - timedelta(days=days),
        )
    return sample_state(user_id)


def unload_sample(user_id: str) -> dict[str, Any]:
    get_book().remove_account(_account_id(user_id), user_id=user_id)
    return sample_state(user_id)
