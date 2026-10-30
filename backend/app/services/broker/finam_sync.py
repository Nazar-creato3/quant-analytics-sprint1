"""Load a user's Finam account into the portfolio book.

Trades come from ``/trades`` (explicit side and size); cash movements,
commissions, taxes and income come from ``/transactions`` (rows that carry
a ``trade`` block are skipped there, so a trade is never counted twice).
Positions are then reconciled to ``GetAccount`` exactly as for T-Bank.
History is read in 30-day windows from the account opening date.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.broker.finam_api import FinamApiError, FinamClient, bare_ticker, dec, money, parse_ts
from app.services.portfolio_book.service import ensure_account, record_transactions
from app.services.portfolio_book.store import get_book

logger = get_logger(__name__)

VENUE = "finam"
_WINDOW = timedelta(days=30)
_OVERLAP = timedelta(days=5)
_SYNC_LOCK_TTL = 300


def book_mode_for(account_mode: str) -> str:
    return "live" if str(account_mode).lower() == "live" else "paper"


def book_account_id(mode: str, broker_account_id: str, user_id: str) -> str:
    return f"{mode}:{VENUE}:{broker_account_id}:{user_id}"


def map_trade(tr: dict[str, Any]) -> dict[str, Any] | None:
    size = dec(tr.get("size")) or Decimal("0")
    price = dec(tr.get("price")) or Decimal("0")
    if size == 0:
        return None
    sign = Decimal("1") if str(tr.get("side") or "") == "SIDE_BUY" else Decimal("-1")
    return {
        "kind": "trade",
        "ticker": bare_ticker(str(tr.get("symbol") or "")),
        "qty": sign * abs(size),
        "amount": abs(size * price),
        "ccy": str(tr.get("currency") or "RUB").upper(),
        "event_time": parse_ts(tr.get("timestamp")) or datetime.now(timezone.utc),
    }


def map_transaction(tx: dict[str, Any]) -> dict[str, Any] | None:
    if tx.get("trade"):
        return None  # booked from /trades
    category = str(tx.get("transaction_category") or tx.get("category") or "OTHERS").upper()
    change, ccy = money(tx.get("change"))
    change = change or Decimal("0")
    ticker = bare_ticker(str(tx.get("symbol") or "")) or "CASH"
    name = str(tx.get("transaction_name") or "").lower()
    base = {"ccy": ccy, "event_time": parse_ts(tx.get("timestamp")) or datetime.now(timezone.utc)}
    if category == "DEPOSIT":
        return {**base, "kind": "deposit", "ticker": "CASH", "qty": Decimal("0"), "amount": abs(change)}
    if category == "WITHDRAW":
        return {**base, "kind": "withdrawal", "ticker": "CASH", "qty": Decimal("0"), "amount": abs(change)}
    if category == "INCOME":
        kind = "coupon" if "купон" in name or "coupon" in name else "dividend"
        return {**base, "kind": kind, "ticker": ticker, "qty": Decimal("0"), "amount": abs(change)}
    if category in {"COMMISSION", "FINE"}:
        kind = "fee" if change <= 0 else "other"
        return {**base, "kind": kind, "ticker": ticker, "qty": Decimal("0"), "amount": abs(change)}
    if category == "TAX":
        kind = "tax" if change <= 0 else "other"
        return {**base, "kind": kind, "ticker": ticker, "qty": Decimal("0"), "amount": abs(change)}
    if category == "TRANSFER":
        qty = dec(tx.get("change_qty")) or Decimal("0")
        if qty != 0:
            return {**base, "kind": "transfer", "ticker": ticker, "qty": qty, "amount": abs(change)}
    if change == 0:
        return None
    return {**base, "kind": "other", "ticker": ticker, "qty": Decimal("0"), "amount": change}


def _last_event(book_account: str, user_id: str, mode: str) -> datetime | None:
    rows = [t for t in get_book().transactions(user_id=user_id, mode=mode) if t.account_id == book_account]  # type: ignore[arg-type]
    return max((t.event_time for t in rows), default=None)


def _reconcile(account: dict[str, Any], *, acc_id: str, user_id: str, mode: str, broker_id: str) -> list[dict[str, Any]]:
    broker: dict[str, tuple[Decimal, Decimal, str]] = {}
    for p in account.get("positions") or []:
        ticker = bare_ticker(str(p.get("symbol") or ""))
        if not ticker:
            continue
        qty = dec(p.get("quantity")) or Decimal("0")
        avg = dec(p.get("average_price")) or dec(p.get("current_price")) or Decimal("0")
        ccy = str(p.get("average_price_currency") or p.get("current_price_currency") or "RUB").upper()
        prev = broker.get(ticker)
        broker[ticker] = ((prev[0] if prev else Decimal("0")) + qty, avg, ccy)
    held: dict[str, Decimal] = {}
    for pos in get_book().positions(user_id=user_id, mode=mode):  # type: ignore[arg-type]
        if pos.account_id == acc_id:
            held[pos.ticker] = held.get(pos.ticker, Decimal("0")) + pos.qty
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%S%f")
    rows = []
    for ticker in sorted(set(broker) | set(held)):
        want, avg, ccy = broker.get(ticker, (Decimal("0"), Decimal("0"), "RUB"))
        diff = want - held.get(ticker, Decimal("0"))
        if diff == 0:
            continue
        rows.append(
            {
                "account_id": acc_id,
                "user_id": user_id,
                "mode": mode,
                "venue": VENUE,
                "external_id": f"{broker_id}:reconcile:{ticker}:{stamp}",
                "kind": "transfer",
                "instrument_id": ticker,
                "ticker": ticker,
                "qty": diff,
                "amount": abs(diff * avg),
                "ccy": ccy,
                "event_time": now,
            }
        )
    record_transactions(rows)
    return [{"ticker": r["ticker"], "qty": str(r["qty"])} for r in rows]


async def _sync_one(client: FinamClient, broker_id: str, *, user_id: str, mode: str, full: bool) -> dict[str, Any]:
    acc_id = book_account_id(mode, broker_id, user_id)
    ensure_account(account_id=acc_id, user_id=user_id, venue=VENUE, mode=mode, source="broker_sync", status="syncing")  # type: ignore[arg-type]
    account = await client.get_account(broker_id)
    firsts = [
        parse_ts(account.get(k))
        for k in ("first_trade_date", "first_non_trade_date", "open_account_date")
    ]
    opened = min((d for d in firsts if d is not None), default=datetime(2018, 1, 1, tzinfo=timezone.utc))
    last = None if full else _last_event(acc_id, user_id, mode)
    start = (last - _OVERLAP) if last else opened
    end = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    cursor = start
    while cursor < end:
        stop = min(cursor + _WINDOW, end)
        for tr in await client.trades(broker_id, cursor, stop):
            mapped = map_trade(tr)
            ext = str(tr.get("trade_id") or "")
            if mapped and ext:
                rows.append({"external_id": f"{broker_id}:trade:{ext}", **mapped})
        for tx in await client.transactions(broker_id, cursor, stop):
            mapped = map_transaction(tx)
            ext = str(tx.get("id") or "")
            if mapped and ext:
                rows.append({"external_id": f"{broker_id}:tx:{ext}", **mapped})
        cursor = stop
    for r in rows:
        r.update({"account_id": acc_id, "user_id": user_id, "mode": mode, "venue": VENUE, "instrument_id": r["ticker"]})
    rows.sort(key=lambda r: r["event_time"])
    added, dupes = record_transactions(rows)
    reconciled = _reconcile(account, acc_id=acc_id, user_id=user_id, mode=mode, broker_id=broker_id)
    equity = dec(account.get("equity"))
    ensure_account(account_id=acc_id, user_id=user_id, venue=VENUE, mode=mode, source="broker_sync", status="ok")  # type: ignore[arg-type]
    return {
        "broker_account_id": broker_id,
        "book_account_id": acc_id,
        "name": f"Счёт {broker_id}",
        "access": "read_only",
        "added": added,
        "duplicates": dupes,
        "positions": len(account.get("positions") or []),
        "total_rub": float(equity) if equity is not None else None,
        "reconciled": reconciled,
        "error": None,
    }


async def sync_finam_secret(
    secret: str,
    *,
    user_id: str,
    account_mode: str,
    full: bool = False,
    client: FinamClient | None = None,
) -> dict[str, Any]:
    mode = book_mode_for(account_mode)
    client = client or FinamClient(secret)
    details = await client.token_details()
    if not details.account_ids:
        raise FinamApiError("not_found", "По этому токену Финама нет счетов")
    results = []
    for broker_id in details.account_ids:
        try:
            out = await _sync_one(client, broker_id, user_id=user_id, mode=mode, full=full)
            out["access"] = "read_only" if details.readonly else "full"
            results.append(out)
        except FinamApiError as exc:
            results.append(
                {
                    "broker_account_id": broker_id,
                    "book_account_id": book_account_id(mode, broker_id, user_id),
                    "name": f"Счёт {broker_id}",
                    "access": "read_only" if details.readonly else "full",
                    "added": 0,
                    "duplicates": 0,
                    "positions": 0,
                    "total_rub": None,
                    "reconciled": [],
                    "error": exc.message,
                }
            )
    logger.info("finam_sync_done", user_id=user_id, mode=mode, accounts=len(results))
    return {
        "venue": VENUE,
        "mode": mode,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "accounts": results,
        "total_rub": round(sum(r["total_rub"] or 0.0 for r in results), 2),
        "ok": all(r["error"] is None for r in results),
    }


async def sync_user_finam(db: AsyncSession, *, user_id: str, account_mode: str, full: bool = False) -> dict[str, Any]:
    from app.services.trading_keys.resolver import UserTradingKeyNotFound, get_active_user_credentials
    from app.utils.cache import cache_lock_acquire, cache_lock_release

    try:
        creds = await get_active_user_credentials(
            db, user_id=user_id, venue="finam", account_mode=account_mode, action="portfolio_sync"
        )
    except UserTradingKeyNotFound as exc:
        raise FinamApiError("not_found", "Счёт Финама не подключён") from exc
    secret = str(creds.credentials.get("token") or creds.credentials.get("api_key") or "")
    lock = f"finam_sync:{user_id}:{account_mode}"
    if not await cache_lock_acquire(lock, ttl=_SYNC_LOCK_TTL):
        raise FinamApiError("busy", "Загрузка счёта уже идёт, обновите страницу через минуту")
    try:
        out = await sync_finam_secret(secret, user_id=user_id, account_mode=account_mode, full=full)
    finally:
        await cache_lock_release(lock)
    await db.commit()
    return out
