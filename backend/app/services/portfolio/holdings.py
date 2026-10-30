"""Current book holdings used as risk-analytics weights."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Maneuver
from app.services.macro.sector_seed import sector_for_symbol
from app.services.portfolio.exposure import OPEN_EXPOSURE_STATUSES
from app.services.portfolio.live_equity import _open_maneuvers
from app.services.portfolio.risk_analytics_math import HoldingSpec
from app.services.portfolio.user_scope import get_user_by_email
from app.utils.json_safe import coerce_finite_float


@dataclass(frozen=True)
class BookHoldings:
    holdings: list[HoldingSpec]
    owner_user_id: str | None
    owner_email: str | None


def _sector_for(maneuver: Maneuver) -> str:
    if maneuver.sector_at_entry:
        return str(maneuver.sector_at_entry)
    mapped = sector_for_symbol(maneuver.ticker)
    if mapped:
        return mapped[0]
    return "unknown"


def _signed_notional(maneuver: Maneuver) -> float:
    size = abs(coerce_finite_float(maneuver.position_size_usd, 0.0))
    direction = str(getattr(maneuver.direction, "value", maneuver.direction) or "long").lower()
    if direction == "short":
        return -size
    return size


async def current_book_holdings(
    db: AsyncSession,
    *,
    owner_user_id: str | None = None,
    owner_email: str | None = None,
) -> BookHoldings:
    """Aggregate open maneuvers by ticker into signed notionals."""
    user_id = owner_user_id
    email = owner_email
    if user_id is None and email:
        user = await get_user_by_email(db, email)
        user_id = user.id if user else None
        email = user.email if user else email

    maneuvers = await _open_maneuvers(db, owner_user_id=user_id)
    buckets: dict[str, tuple[float, str]] = {}
    for maneuver in maneuvers:
        if maneuver.status not in OPEN_EXPOSURE_STATUSES and str(maneuver.status) not in {
            "approved",
            "filled",
            "executing",
        }:
            continue
        symbol = str(maneuver.ticker or "").strip().upper()
        if not symbol:
            continue
        signed = _signed_notional(maneuver)
        prev_notional, prev_sector = buckets.get(symbol, (0.0, _sector_for(maneuver)))
        buckets[symbol] = (prev_notional + signed, prev_sector or _sector_for(maneuver))

    holdings = [
        HoldingSpec(symbol=sym, notional_usd=notional, sector=sector)
        for sym, (notional, sector) in sorted(buckets.items())
        if abs(notional) > 1e-8
    ]
    return BookHoldings(holdings=holdings, owner_user_id=user_id, owner_email=email)
