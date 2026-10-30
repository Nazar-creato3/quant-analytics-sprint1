"""Portfolio book (Prompt 05). Paper and live never share rows.

Kept in memory for speed, mirrored to a JSON snapshot in production so the
book survives restarts and both API workers see the same positions (it used
to be per-process: a synced broker account vanished on restart and showed up
in only one worker). Persistence is on when APP_ENV is production/staging or
QA_BOOK_PERSIST=1; tests stay in memory.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import os
from threading import Lock
from typing import Any, Literal

Mode = Literal["paper", "live"]
TxnType = Literal[
    "trade",
    "deposit",
    "withdrawal",
    "dividend",
    "coupon",
    "fee",
    "tax",
    "variation_margin",
    "transfer",
    "other",
]


class BookModeError(Exception):
    """Paper and live must not mix."""


class DuplicateExternalId(Exception):
    """(venue, external_id) already recorded."""


@dataclass(frozen=True)
class Account:
    id: str
    user_id: str
    venue: str
    mode: Mode
    source: str
    status: str
    last_sync: datetime | None
    history_depth_days: int


@dataclass(frozen=True)
class Transaction:
    id: int
    account_id: str
    user_id: str
    mode: Mode
    venue: str
    external_id: str
    kind: TxnType
    instrument_id: str
    ticker: str
    qty: Decimal
    amount: Decimal
    ccy: str
    event_time: datetime
    recorded_at: datetime
    version: int


@dataclass(frozen=True)
class BookPosition:
    account_id: str
    user_id: str
    mode: Mode
    instrument_id: str
    ticker: str
    qty: Decimal
    ccy: str


@dataclass
class PortfolioBook:
    _accounts: dict[str, Account] = field(default_factory=dict)
    _txns: list[Transaction] = field(default_factory=list)
    _ext: set[tuple[str, str, str]] = field(default_factory=set)
    _lock: Lock = field(default_factory=Lock)
    _loaded_mtime: float = -1.0

    # ── persistence ────────────────────────────────────────────────────────
    @staticmethod
    def _persist_on() -> bool:
        from app.services.qa import durable_store

        return durable_store.enabled()

    def _sync(self) -> None:
        """Reload from disk if another worker wrote a newer snapshot. Caller holds _lock."""
        if not self._persist_on():
            return
        from app.services.qa import durable_store

        path = durable_store._path("portfolio_book")  # noqa: SLF001 - same package family
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        if mtime <= self._loaded_mtime:
            return
        data = durable_store.load("portfolio_book")
        accounts: dict[str, Account] = {}
        for a in data.get("accounts") or []:
            accounts[a["id"]] = Account(
                id=a["id"],
                user_id=a["user_id"],
                venue=a["venue"],
                mode=a["mode"],
                source=a["source"],
                status=a["status"],
                last_sync=datetime.fromisoformat(a["last_sync"]) if a.get("last_sync") else None,
                history_depth_days=int(a.get("history_depth_days") or 0),
            )
        txns: list[Transaction] = []
        for t in data.get("txns") or []:
            txns.append(
                Transaction(
                    id=int(t["id"]),
                    account_id=t["account_id"],
                    user_id=t["user_id"],
                    mode=t["mode"],
                    venue=t["venue"],
                    external_id=t["external_id"],
                    kind=t["kind"],
                    instrument_id=t["instrument_id"],
                    ticker=t["ticker"],
                    qty=Decimal(t["qty"]),
                    amount=Decimal(t["amount"]),
                    ccy=t["ccy"],
                    event_time=datetime.fromisoformat(t["event_time"]),
                    recorded_at=datetime.fromisoformat(t["recorded_at"]),
                    version=int(t["version"]),
                )
            )
        self._accounts = accounts
        self._txns = txns
        self._ext = {(t.user_id, t.venue, t.external_id) for t in txns}
        self._loaded_mtime = mtime

    def _flush(self) -> None:
        """Write the snapshot. Caller holds _lock."""
        if not self._persist_on():
            return
        from app.services.qa import durable_store

        def acc(a: Account) -> dict[str, Any]:
            return {
                "id": a.id,
                "user_id": a.user_id,
                "venue": a.venue,
                "mode": a.mode,
                "source": a.source,
                "status": a.status,
                "last_sync": a.last_sync.isoformat() if a.last_sync else None,
                "history_depth_days": a.history_depth_days,
            }

        def txn(t: Transaction) -> dict[str, Any]:
            return {
                "id": t.id,
                "account_id": t.account_id,
                "user_id": t.user_id,
                "mode": t.mode,
                "venue": t.venue,
                "external_id": t.external_id,
                "kind": t.kind,
                "instrument_id": t.instrument_id,
                "ticker": t.ticker,
                "qty": str(t.qty),
                "amount": str(t.amount),
                "ccy": t.ccy,
                "event_time": t.event_time.isoformat(),
                "recorded_at": t.recorded_at.isoformat(),
                "version": t.version,
            }

        durable_store.save(
            "portfolio_book",
            {"accounts": [acc(a) for a in self._accounts.values()], "txns": [txn(t) for t in self._txns]},
        )
        try:
            self._loaded_mtime = durable_store._path("portfolio_book").stat().st_mtime  # noqa: SLF001
        except OSError:
            pass

    def upsert_account(self, account: Account) -> Account:
        with self._lock:
            self._sync()
            existing = self._accounts.get(account.id)
            if existing and existing.mode != account.mode:
                raise BookModeError("cannot change account mode")
            self._accounts[account.id] = account
            self._flush()
            return account

    def account(self, account_id: str) -> Account:
        with self._lock:
            self._sync()
            return self._accounts[account_id]

    def append_txn(self, fields: dict[str, Any]) -> Transaction:
        with self._lock:
            self._sync()
            row, added = self._append_locked(fields)
            if added:
                self._flush()
            return row

    def append_txns(self, rows: list[dict[str, Any]]) -> tuple[int, int]:
        """Bulk append under one lock and one snapshot write. Returns (added, duplicates)."""
        added = 0
        dupes = 0
        with self._lock:
            self._sync()
            for fields in rows:
                _, is_new = self._append_locked(fields)
                if is_new:
                    added += 1
                else:
                    dupes += 1
            if added:
                self._flush()
        return added, dupes

    def _append_locked(self, fields: dict[str, Any]) -> tuple[Transaction, bool]:
        """Caller holds _lock. Returns (row, added); an existing external_id is returned as is."""
        account = self._accounts[str(fields["account_id"])]
        mode: Mode = fields["mode"]
        if account.mode != mode:
            raise BookModeError("transaction mode must match account")
        user_id = str(fields["user_id"])
        key = (user_id, str(fields["venue"]), str(fields["external_id"]))
        if key in self._ext:
            for row in self._txns:
                if (row.user_id, row.venue, row.external_id) == key:
                    return row, False
            raise DuplicateExternalId(str(key))
        prior = [
            t
            for t in self._txns
            if t.user_id == user_id
            and t.venue == key[1]
            and t.external_id.startswith(str(fields["external_id"]) + "#v")
        ]
        version = int(fields.get("version") or (len(prior) + 1))
        row = Transaction(
            id=len(self._txns) + 1,
            account_id=account.id,
            user_id=str(fields["user_id"]),
            mode=mode,
            venue=str(fields["venue"]),
            external_id=str(fields["external_id"]),
            kind=fields["kind"],
            instrument_id=str(fields["instrument_id"]),
            ticker=str(fields["ticker"]).upper(),
            qty=Decimal(str(fields["qty"])),
            amount=Decimal(str(fields["amount"])),
            ccy=str(fields["ccy"]),
            event_time=fields["event_time"],
            recorded_at=fields.get("recorded_at") or datetime.now(timezone.utc),
            version=version,
        )
        self._txns.append(row)
        self._ext.add(key)
        return row, True

    def correct_txn(self, venue: str, external_id: str, *, user_id: str, **updates: Any) -> Transaction:
        """New version; original row stays."""
        with self._lock:
            self._sync()
            original = next(
                t
                for t in self._txns
                if t.venue == venue and t.external_id == external_id and t.user_id == user_id
            )
        payload = {
            "account_id": original.account_id,
            "user_id": original.user_id,
            "mode": original.mode,
            "venue": original.venue,
            "external_id": f"{external_id}#v{original.version + 1}",
            "kind": updates.get("kind", original.kind),
            "instrument_id": updates.get("instrument_id", original.instrument_id),
            "ticker": updates.get("ticker", original.ticker),
            "qty": updates.get("qty", original.qty),
            "amount": updates.get("amount", original.amount),
            "ccy": updates.get("ccy", original.ccy),
            "event_time": updates.get("event_time", original.event_time),
            "version": original.version + 1,
        }
        return self.append_txn(payload)

    def positions(
        self,
        *,
        user_id: str,
        mode: Mode,
        as_of_event: datetime | None = None,
        as_of_recorded: datetime | None = None,
    ) -> list[BookPosition]:
        with self._lock:
            self._sync()
            rows = [t for t in self._txns if t.user_id == user_id and t.mode == mode]
        if as_of_event is not None:
            rows = [t for t in rows if t.event_time <= as_of_event]
        if as_of_recorded is not None:
            rows = [t for t in rows if t.recorded_at <= as_of_recorded]
        latest: dict[tuple[str, str], Transaction] = {}
        for t in rows:
            base = t.external_id.split("#v")[0]
            key = (t.account_id, t.ticker, base)
            prev = latest.get(key)
            if prev is None or t.version >= prev.version:
                latest[key] = t
        qty: dict[tuple[str, str, str, str], Decimal] = {}
        ccy: dict[tuple[str, str, str, str], str] = {}
        for t in latest.values():
            if t.kind not in {"trade", "transfer", "variation_margin"}:
                continue
            pk = (t.account_id, t.user_id, t.ticker, t.instrument_id)
            qty[pk] = qty.get(pk, Decimal("0")) + t.qty
            ccy[pk] = t.ccy
        out: list[BookPosition] = []
        for (account_id, uid, ticker, instrument_id), q in qty.items():
            if q == 0:
                continue
            out.append(
                BookPosition(
                    account_id=account_id,
                    user_id=uid,
                    mode=mode,
                    instrument_id=instrument_id,
                    ticker=ticker,
                    qty=q,
                    ccy=ccy[(account_id, uid, ticker, instrument_id)],
                )
            )
        return out

    def transactions(self, *, user_id: str, mode: Mode) -> list[Transaction]:
        with self._lock:
            self._sync()
            return [t for t in self._txns if t.user_id == user_id and t.mode == mode]

    def remove_account(self, account_id: str, *, user_id: str) -> int:
        """Drop one account and its rows (used to unload the sample portfolio)."""
        with self._lock:
            self._sync()
            acc = self._accounts.get(account_id)
            if acc is None or acc.user_id != user_id:
                return 0
            before = len(self._txns)
            self._txns = [t for t in self._txns if t.account_id != account_id]
            self._ext = {(t.user_id, t.venue, t.external_id) for t in self._txns}
            self._accounts.pop(account_id, None)
            self._flush()
            return before - len(self._txns)

    def accounts_for(self, *, user_id: str) -> list[Account]:
        with self._lock:
            self._sync()
            return [a for a in self._accounts.values() if a.user_id == user_id]

    def all_tickers(self) -> list[str]:
        """Every instrument held or traded by anyone — the nightly price-history universe."""
        with self._lock:
            self._sync()
            return sorted({t.ticker.upper() for t in self._txns if t.ticker and t.ticker.upper() != "CASH"})

    def reset(self) -> None:
        with self._lock:
            self._accounts.clear()
            self._txns.clear()
            self._ext.clear()
            self._flush()


_BOOK = PortfolioBook()


def get_book() -> PortfolioBook:
    return _BOOK
