"""Load a user's T-Bank account into the portfolio book.

Operations (trades, fees, taxes, dividends, coupons, cash in/out) come from
``GetOperationsByCursor`` and are written idempotently by operation id. After
the import the book is reconciled against ``GetPortfolio``: any quantity the
history does not explain (transfers from another broker, history older than
the API keeps) is booked as a ``transfer`` at the broker's average price, so
positions always equal what the broker reports.

A live key fills the ``live`` book, a sandbox key the ``paper`` book; the two
never mix. Nothing here places orders.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.broker.tbank_api import (
    TBankAccount,
    TBankApiError,
    TBankClient,
    money,
    money_ccy,
    parse_ts,
)
from app.services.portfolio_book.service import ensure_account, record_transactions
from app.services.portfolio_book.store import get_book

logger = get_logger(__name__)

VENUE = "tbank"
# Re-read a few days back on every sync: the broker settles some operations late.
_OVERLAP = timedelta(days=5)
_SYNC_LOCK_TTL = 300

_BUY = {
    "OPERATION_TYPE_BUY",
    "OPERATION_TYPE_BUY_CARD",
    "OPERATION_TYPE_BUY_MARGIN",
    "OPERATION_TYPE_DELIVERY_BUY",
}
_SELL = {
    "OPERATION_TYPE_SELL",
    "OPERATION_TYPE_SELL_CARD",
    "OPERATION_TYPE_SELL_MARGIN",
    "OPERATION_TYPE_DELIVERY_SELL",
    "OPERATION_TYPE_BOND_REPAYMENT_FULL",
}
_DEPOSIT = {"OPERATION_TYPE_INPUT", "OPERATION_TYPE_INP_MULTI", "OPERATION_TYPE_INPUT_SWIFT", "OPERATION_TYPE_INPUT_ACQUIRING"}
_WITHDRAWAL = {"OPERATION_TYPE_OUTPUT", "OPERATION_TYPE_OUT_MULTI", "OPERATION_TYPE_OUTPUT_SWIFT", "OPERATION_TYPE_OUTPUT_ACQUIRING"}
_DIVIDEND = {"OPERATION_TYPE_DIVIDEND", "OPERATION_TYPE_DIV_EXT", "OPERATION_TYPE_DIVIDEND_TRANSFER"}
_COUPON = {"OPERATION_TYPE_COUPON"}
_TAX = {
    "OPERATION_TYPE_TAX",
    "OPERATION_TYPE_BOND_TAX",
    "OPERATION_TYPE_DIVIDEND_TAX",
    "OPERATION_TYPE_BENEFIT_TAX",
    "OPERATION_TYPE_TAX_CORRECTION",
    "OPERATION_TYPE_TAX_PROGRESSIVE",
    "OPERATION_TYPE_BOND_TAX_PROGRESSIVE",
    "OPERATION_TYPE_DIVIDEND_TAX_PROGRESSIVE",
    "OPERATION_TYPE_BENEFIT_TAX_PROGRESSIVE",
    "OPERATION_TYPE_TAX_CORRECTION_PROGRESSIVE",
    "OPERATION_TYPE_TAX_REPO_PROGRESSIVE",
    "OPERATION_TYPE_TAX_REPO",
    "OPERATION_TYPE_TAX_REPO_HOLD",
    "OPERATION_TYPE_TAX_REPO_REFUND",
    "OPERATION_TYPE_TAX_REPO_HOLD_PROGRESSIVE",
    "OPERATION_TYPE_TAX_REPO_REFUND_PROGRESSIVE",
    "OPERATION_TYPE_TAX_CORRECTION_COUPON",
}
_FEE = {
    "OPERATION_TYPE_BROKER_FEE",
    "OPERATION_TYPE_SERVICE_FEE",
    "OPERATION_TYPE_MARGIN_FEE",
    "OPERATION_TYPE_SUCCESS_FEE",
    "OPERATION_TYPE_OUT_FEE",
    "OPERATION_TYPE_TRACK_MFEE",
    "OPERATION_TYPE_TRACK_PFEE",
    "OPERATION_TYPE_ADVICE_FEE",
    "OPERATION_TYPE_OUTPUT_PENALTY",
    "OPERATION_TYPE_OVER_COM",
    "OPERATION_TYPE_CASH_FEE",
    "OPERATION_TYPE_OUT_STAMP_DUTY",
}
_SEC_IN = {"OPERATION_TYPE_INPUT_SECURITIES", "OPERATION_TYPE_TRANS_IIS_BS", "OPERATION_TYPE_TRANS_BS_BS"}
_SEC_OUT = {"OPERATION_TYPE_OUTPUT_SECURITIES"}
_VARMARGIN = {"OPERATION_TYPE_ACCRUING_VARMARGIN", "OPERATION_TYPE_WRITING_OFF_VARMARGIN"}
# Cash-like positions in GetPortfolio: not securities, not reconciled as holdings.
_CASH_TYPES = {"currency"}


@dataclass
class AccountSyncResult:
    broker_account_id: str
    book_account_id: str
    name: str
    access: str
    added: int = 0
    duplicates: int = 0
    reconciled: list[dict[str, Any]] = field(default_factory=list)
    positions: int = 0
    total_rub: float | None = None
    error: str | None = None


def book_mode_for(account_mode: str) -> str:
    return "live" if str(account_mode).lower() == "live" else "paper"


def book_account_id(mode: str, broker_account_id: str, user_id: str) -> str:
    return f"{mode}:{VENUE}:{broker_account_id}:{user_id}"


def _qty_done(op: dict[str, Any]) -> Decimal:
    qty = Decimal(str(op.get("quantity") or 0))
    rest = Decimal(str(op.get("quantityRest") or 0))
    done = op.get("quantityDone")
    if done not in (None, "", "0", 0):
        return Decimal(str(done))
    return qty - rest if qty > rest else qty


def map_operation(op: dict[str, Any], *, ticker: str) -> dict[str, Any] | None:
    """One broker operation → book fields (without account/user). None = skip.

    Book convention (same as the sample book): ``amount`` is a positive money
    figure, the sign of ``qty`` carries the trade direction.
    """
    kind_raw = str(op.get("type") or "")
    payment = money(op.get("payment")) or Decimal("0")
    ccy = money_ccy(op.get("payment"))
    when = parse_ts(op.get("date")) or datetime.now(timezone.utc)
    base = {"event_time": when, "ccy": ccy}

    if kind_raw in _BUY or kind_raw in _SELL:
        qty = _qty_done(op)
        if qty == 0:
            return None
        sign = Decimal("1") if kind_raw in _BUY else Decimal("-1")
        return {**base, "kind": "trade", "ticker": ticker, "qty": sign * abs(qty), "amount": abs(payment)}
    if kind_raw in _SEC_IN or kind_raw in _SEC_OUT:
        qty = _qty_done(op)
        if qty == 0:
            return None
        sign = Decimal("1") if kind_raw in _SEC_IN else Decimal("-1")
        price = money(op.get("price")) or Decimal("0")
        return {**base, "kind": "transfer", "ticker": ticker, "qty": sign * abs(qty), "amount": abs(price * qty)}
    if kind_raw in _DEPOSIT:
        return {**base, "kind": "deposit", "ticker": "CASH", "qty": Decimal("0"), "amount": abs(payment)}
    if kind_raw in _WITHDRAWAL:
        return {**base, "kind": "withdrawal", "ticker": "CASH", "qty": Decimal("0"), "amount": abs(payment)}
    if kind_raw in _DIVIDEND:
        return {**base, "kind": "dividend", "ticker": ticker or "CASH", "qty": Decimal("0"), "amount": abs(payment)}
    if kind_raw in _COUPON:
        return {**base, "kind": "coupon", "ticker": ticker or "CASH", "qty": Decimal("0"), "amount": abs(payment)}
    if kind_raw in _TAX:
        # A positive payment is a refund (tax correction) — income, not a tax.
        kind = "tax" if payment <= 0 else "other"
        return {**base, "kind": kind, "ticker": ticker or "CASH", "qty": Decimal("0"), "amount": abs(payment)}
    if kind_raw in _FEE:
        kind = "fee" if payment <= 0 else "other"
        return {**base, "kind": kind, "ticker": ticker or "CASH", "qty": Decimal("0"), "amount": abs(payment)}
    if kind_raw in _VARMARGIN:
        return {**base, "kind": "variation_margin", "ticker": ticker or "CASH", "qty": Decimal("0"), "amount": payment}
    if payment == 0:
        return None
    return {**base, "kind": "other", "ticker": ticker or "CASH", "qty": Decimal("0"), "amount": payment}


async def _ticker_for(client: TBankClient, op: dict[str, Any]) -> str:
    ticker = str(op.get("ticker") or "").strip().upper()
    if ticker:
        return ticker
    figi = str(op.get("figi") or "").strip()
    if not figi:
        return ""
    try:
        return (await client.instrument_by_figi(figi)).ticker
    except TBankApiError:
        return figi


def _last_event(book_account: str, user_id: str, mode: str) -> datetime | None:
    rows = [t for t in get_book().transactions(user_id=user_id, mode=mode) if t.account_id == book_account]  # type: ignore[arg-type]
    if not rows:
        return None
    return max(t.event_time for t in rows)


async def _sync_one(
    client: TBankClient,
    account: TBankAccount,
    *,
    user_id: str,
    mode: str,
    full: bool,
) -> AccountSyncResult:
    acc_id = book_account_id(mode, account.id, user_id)
    result = AccountSyncResult(
        broker_account_id=account.id,
        book_account_id=acc_id,
        name=account.name or "Брокерский счёт",
        access="full" if account.can_trade else "read_only",
    )
    ensure_account(
        account_id=acc_id,
        user_id=user_id,
        venue=VENUE,
        mode=mode,  # type: ignore[arg-type]
        source="broker_sync",
        status="syncing",
    )
    last = None if full else _last_event(acc_id, user_id, mode)
    start = (last - _OVERLAP) if last else (account.opened_date or datetime(2015, 1, 1, tzinfo=timezone.utc))
    rows: list[dict[str, Any]] = []
    async for op in client.iter_operations(account.id, start=start, end=datetime.now(timezone.utc)):
        op_id = str(op.get("id") or "")
        if not op_id:
            continue
        ticker = await _ticker_for(client, op)
        mapped = map_operation(op, ticker=ticker)
        if mapped is None:
            continue
        rows.append(
            {
                "account_id": acc_id,
                "user_id": user_id,
                "mode": mode,
                "venue": VENUE,
                "external_id": f"{account.id}:{op_id}",
                "instrument_id": mapped["ticker"],
                **mapped,
            }
        )
    rows.sort(key=lambda r: r["event_time"])
    result.added, result.duplicates = record_transactions(rows)

    portfolio = await client.get_portfolio(account.id)
    total = money(portfolio.get("totalAmountPortfolio"))
    result.total_rub = float(total) if total is not None else None
    result.reconciled = _reconcile(portfolio, acc_id=acc_id, user_id=user_id, mode=mode, broker_account_id=account.id)
    result.positions = sum(
        1 for p in portfolio.get("positions") or [] if str(p.get("instrumentType") or "") not in _CASH_TYPES
    )
    ensure_account(
        account_id=acc_id,
        user_id=user_id,
        venue=VENUE,
        mode=mode,  # type: ignore[arg-type]
        source="broker_sync",
        status="ok",
    )
    return result


def _reconcile(
    portfolio: dict[str, Any],
    *,
    acc_id: str,
    user_id: str,
    mode: str,
    broker_account_id: str,
) -> list[dict[str, Any]]:
    """Book transfers so that book quantities equal the broker's portfolio."""
    broker: dict[str, tuple[Decimal, Decimal, str]] = {}
    for p in portfolio.get("positions") or []:
        if str(p.get("instrumentType") or "") in _CASH_TYPES:
            continue
        ticker = str(p.get("ticker") or p.get("figi") or "").upper()
        if not ticker:
            continue
        qty = money(p.get("quantity")) or Decimal("0")
        avg = money(p.get("averagePositionPrice")) or money(p.get("currentPrice")) or Decimal("0")
        ccy = money_ccy(p.get("averagePositionPrice") or p.get("currentPrice"))
        prev = broker.get(ticker)
        broker[ticker] = ((prev[0] if prev else Decimal("0")) + qty, avg, ccy)

    held: dict[str, Decimal] = {}
    for pos in get_book().positions(user_id=user_id, mode=mode):  # type: ignore[arg-type]
        if pos.account_id == acc_id:
            held[pos.ticker] = held.get(pos.ticker, Decimal("0")) + pos.qty

    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%S%f")
    rows: list[dict[str, Any]] = []
    for ticker in sorted(set(broker) | set(held)):
        want, avg, ccy = broker.get(ticker, (Decimal("0"), Decimal("0"), "RUB"))
        have = held.get(ticker, Decimal("0"))
        diff = want - have
        if diff == 0:
            continue
        rows.append(
            {
                "account_id": acc_id,
                "user_id": user_id,
                "mode": mode,
                "venue": VENUE,
                "external_id": f"{broker_account_id}:reconcile:{ticker}:{stamp}",
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


async def sync_tbank_token(
    token: str,
    *,
    user_id: str,
    account_mode: str,
    full: bool = False,
    client: TBankClient | None = None,
) -> dict[str, Any]:
    """Sync every open, readable brokerage account behind one token."""
    mode = book_mode_for(account_mode)
    client = client or TBankClient(token, sandbox=(mode == "paper"))
    accounts = [a for a in await client.get_accounts() if a.is_open and a.readable and a.is_brokerage]
    if not accounts:
        raise TBankApiError("not_found", "По этому токену нет открытых брокерских счетов")
    results: list[AccountSyncResult] = []
    for account in accounts:
        try:
            results.append(await _sync_one(client, account, user_id=user_id, mode=mode, full=full))
        except TBankApiError as exc:
            results.append(
                AccountSyncResult(
                    broker_account_id=account.id,
                    book_account_id=book_account_id(mode, account.id, user_id),
                    name=account.name or "Брокерский счёт",
                    access="full" if account.can_trade else "read_only",
                    error=exc.message,
                )
            )
    logger.info(
        "tbank_sync_done",
        user_id=user_id,
        mode=mode,
        accounts=len(results),
        added=sum(r.added for r in results),
        errors=sum(1 for r in results if r.error),
    )
    return {
        "venue": VENUE,
        "mode": mode,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "accounts": [r.__dict__ for r in results],
        "total_rub": round(sum(r.total_rub or 0.0 for r in results), 2),
        "ok": all(r.error is None for r in results),
    }


async def sync_user_tbank(
    db: AsyncSession,
    *,
    user_id: str,
    account_mode: str,
    full: bool = False,
) -> dict[str, Any]:
    """Load the user's stored token and sync. One sync per user and mode at a time."""
    from app.services.trading_keys.resolver import UserTradingKeyNotFound, get_active_user_credentials
    from app.utils.cache import cache_lock_acquire, cache_lock_release

    try:
        creds = await get_active_user_credentials(
            db, user_id=user_id, venue="tinkoff", account_mode=account_mode, action="portfolio_sync"
        )
    except UserTradingKeyNotFound as exc:
        raise TBankApiError("not_found", "Счёт Т-Банка не подключён") from exc
    token = str(creds.credentials.get("token") or creds.credentials.get("api_key") or "")
    lock = f"tbank_sync:{user_id}:{account_mode}"
    if not await cache_lock_acquire(lock, ttl=_SYNC_LOCK_TTL):
        raise TBankApiError("busy", "Загрузка счёта уже идёт, обновите страницу через минуту")
    try:
        out = await sync_tbank_token(token, user_id=user_id, account_mode=account_mode, full=full)
    finally:
        await cache_lock_release(lock)
    await db.commit()  # persists the key audit row written by the resolver
    return out


def synced_accounts(user_id: str, mode: str) -> list[dict[str, Any]]:
    book = get_book()
    out = []
    for acc in book.accounts_for(user_id=user_id):
        if acc.venue != VENUE or acc.mode != mode:
            continue
        out.append(
            {
                "id": acc.id,
                "status": acc.status,
                "last_sync": acc.last_sync.isoformat() if acc.last_sync else None,
            }
        )
    return out
