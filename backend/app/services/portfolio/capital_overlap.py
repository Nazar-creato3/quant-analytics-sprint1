"""One ticker should not eat capital from grid and maneuvers at once."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.services.grid.execution import compute_open_positions

logger = get_logger(__name__)


def grid_occupied_tickers(
    bots: dict[str, Any] | None,
    owner_email: str | None = None,
) -> set[str]:
    if not bots:
        return set()
    data = bots
    if owner_email:
        from app.services.portfolio.user_scope import filter_grid_bots_for_user

        data = filter_grid_bots_for_user(bots, owner_email)
    occupied: set[str] = set()
    for raw in data.values():
        if not isinstance(raw, dict):
            continue
        for pos in compute_open_positions(raw, None):
            ticker = str(pos.get("ticker") or "").strip().upper()
            notional = float(pos.get("notional_usd") or 0.0)
            if ticker and notional > 1.0:
                occupied.add(ticker)
    return occupied


def maneuver_occupied_tickers(maneuvers: list[Any] | None) -> set[str]:
    occupied: set[str] = set()
    for row in maneuvers or []:
        ticker = str(getattr(row, "ticker", None) or "").strip().upper()
        if ticker:
            occupied.add(ticker)
    return occupied


async def maneuver_occupied_tickers_for_email(db: Any, email: str | None) -> set[str]:
    """Open maneuver tickers for this user. Empty on mock/unresolved sessions."""
    from sqlalchemy.ext.asyncio import AsyncSession

    if not email or not isinstance(db, AsyncSession):
        return set()
    try:
        from sqlalchemy import select

        from app.db.models import User
        from app.services.portfolio.live_equity import _open_maneuvers

        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user:
            return set()
        rows = await _open_maneuvers(db, owner_user_id=str(user.id))
        return maneuver_occupied_tickers(rows)
    except Exception as exc:
        logger.warning("occupied tickers unavailable", email=email, error=str(exc)[:200])
        return set()
