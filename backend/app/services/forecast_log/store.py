"""In-memory append-only forecast_log (Prompt 11A). SQL REVOKE is in 0055."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from threading import Lock
from typing import Any

from app.services.forecast_log.hash_chain import GENESIS, row_hash, snapshot_hash


class ImmutableLogError(Exception):
    """UPDATE/DELETE of forecast_log is forbidden."""


@dataclass(frozen=True)
class ForecastLogRow:
    id: int
    issued_at: datetime
    instrument_id: str
    ticker: str
    horizon_days: int
    direction: int
    probability: str
    interval_low: str | None
    interval_high: str | None
    section: str
    model_id: str
    model_version: str
    feature_hash: str
    issued_price: str | None
    issued_price_source: str
    prev_hash: str
    row_hash: str


@dataclass(frozen=True)
class SettlementRow:
    id: int
    log_id: int
    settled_at: datetime
    session_date: date
    actual_price: str
    actual_source: str
    direction_correct: bool
    error: str
    correction_of: int | None
    prev_hash: str
    row_hash: str


@dataclass
class ForecastLogStore:
    _rows: list[ForecastLogRow] = field(default_factory=list)
    _settlements: list[SettlementRow] = field(default_factory=list)
    _snapshots: dict[str, str] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def append(self, fields: dict[str, Any]) -> ForecastLogRow:
        with self._lock:
            prev = self._rows[-1].row_hash if self._rows else GENESIS
            payload = {k: fields[k] for k in sorted(fields)}
            digest = row_hash(prev, payload)
            row = ForecastLogRow(
                id=len(self._rows) + 1,
                issued_at=fields["issued_at"],
                instrument_id=str(fields["instrument_id"]),
                ticker=str(fields["ticker"]),
                horizon_days=int(fields["horizon_days"]),
                direction=int(fields["direction"]),
                probability=str(fields["probability"]),
                interval_low=fields.get("interval_low"),
                interval_high=fields.get("interval_high"),
                section=str(fields["section"]),
                model_id=str(fields["model_id"]),
                model_version=str(fields["model_version"]),
                feature_hash=str(fields["feature_hash"]),
                issued_price=fields.get("issued_price"),
                issued_price_source=str(fields.get("issued_price_source") or "unknown"),
                prev_hash=prev,
                row_hash=digest,
            )
            self._rows.append(row)
            return row

    def append_settlement(self, fields: dict[str, Any]) -> SettlementRow:
        with self._lock:
            prev = self._settlements[-1].row_hash if self._settlements else GENESIS
            payload = {k: fields[k] for k in sorted(fields)}
            digest = row_hash(prev, payload)
            row = SettlementRow(
                id=len(self._settlements) + 1,
                log_id=int(fields["log_id"]),
                settled_at=fields["settled_at"],
                session_date=fields["session_date"],
                actual_price=str(fields["actual_price"]),
                actual_source=str(fields["actual_source"]),
                direction_correct=bool(fields["direction_correct"]),
                error=str(fields["error"]),
                correction_of=fields.get("correction_of"),
                prev_hash=prev,
                row_hash=digest,
            )
            self._settlements.append(row)
            return row

    def update(self, *_a: Any, **_k: Any) -> None:
        raise ImmutableLogError("forecast_log forbids UPDATE")

    def delete(self, *_a: Any, **_k: Any) -> None:
        raise ImmutableLogError("forecast_log forbids DELETE")

    def rows(self) -> list[ForecastLogRow]:
        with self._lock:
            return list(self._rows)

    def settlements(self) -> list[SettlementRow]:
        with self._lock:
            return list(self._settlements)

    def daily_snapshot(self, day: date) -> str:
        with self._lock:
            digest = snapshot_hash([r.row_hash for r in self._rows])
            self._snapshots[day.isoformat()] = digest
            return digest

    def snapshots(self) -> dict[str, str]:
        with self._lock:
            return dict(self._snapshots)

    def reset(self) -> None:
        with self._lock:
            self._rows.clear()
            self._settlements.clear()
            self._snapshots.clear()


_STORE = ForecastLogStore()


def get_store() -> ForecastLogStore:
    return _STORE
