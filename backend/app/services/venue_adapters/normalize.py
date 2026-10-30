"""Map venue operations onto portfolio_book Transaction types."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.services.catalog.resolve import resolve
from app.services.portfolio_book.service import ensure_account, record_transaction

_KIND = {
    "buy": "trade",
    "sell": "trade",
    "trade": "trade",
    "dividend": "dividend",
    "coupon": "coupon",
    "fee": "fee",
    "commission": "fee",
    "tax": "tax",
    "deposit": "deposit",
    "payin": "deposit",
    "withdrawal": "withdrawal",
    "payout": "withdrawal",
    "margin": "variation_margin",
    "variation_margin": "variation_margin",
}


def map_kind(raw: str) -> str:
    return _KIND.get(raw.strip().lower(), "other")


def ingest_operations(
    *,
    user_id: str,
    venue: str,
    mode: str,
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    account_id = f"{mode}:{venue}:{user_id}"
    ensure_account(
        account_id=account_id,
        user_id=user_id,
        venue=venue,
        mode=mode,  # type: ignore[arg-type]
        source="venue_adapter",
        status="syncing",
    )
    accepted = 0
    earliest: datetime | None = None
    for op in operations:
        raw_ticker = str(op.get("ticker") or op.get("instrument") or "CASH")
        try:
            hit = resolve(raw_ticker)
            ticker = hit.symbol
            instrument_id = hit.asset_id
        except (KeyError, ValueError):
            ticker = raw_ticker.upper()
            instrument_id = ticker
        event = op.get("event_time") or datetime.now(timezone.utc)
        if isinstance(event, str):
            event = datetime.fromisoformat(event.replace("Z", "+00:00"))
        qty = Decimal(str(op.get("qty") or "0"))
        if str(op.get("side") or "").lower() == "sell":
            qty = -abs(qty)
        record_transaction(
            account_id=account_id,
            user_id=user_id,
            mode=mode,  # type: ignore[arg-type]
            venue=venue,
            external_id=str(op["external_id"]),
            kind=map_kind(str(op.get("kind") or "other")),
            instrument_id=instrument_id,
            ticker=ticker,
            qty=qty,
            amount=Decimal(str(op.get("amount") or "0")),
            ccy=str(op.get("ccy") or "RUB"),
            event_time=event,
        )
        accepted += 1
        if earliest is None or event < earliest:
            earliest = event
    return {
        "accepted": accepted,
        "account_id": account_id,
        "coverage_from": earliest.isoformat() if earliest else None,
        "venue": venue,
        "mode": mode,
    }
