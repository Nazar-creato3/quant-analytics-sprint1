"""Shared portfolio exposure from live open positions (maneuvers + grid bots)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Maneuver, ManeuverStatus
from app.services.grid.execution import compute_open_positions
from app.utils.cache import cache_get, cache_set
from app.utils.json_safe import coerce_finite_float

logger = get_logger(__name__)

_GRID_KEY = "grid:bots"
_GRID_TTL = 60 * 60 * 24 * 30

# Capital reserved from approval through open position (paper ledger + buying power).
OPEN_EXPOSURE_STATUSES = (
    ManeuverStatus.APPROVED,
    ManeuverStatus.EXECUTING,
    ManeuverStatus.FILLED,
)


@dataclass
class ExposureSnapshot:
    maneuver_usd: float
    grid_usd: float
    open_maneuvers: int
    grid_bots_with_positions: int
    active_grid_bots: int

    @property
    def total_usd(self) -> float:
        return round(self.maneuver_usd + self.grid_usd, 2)


async def maneuver_exposure(
    db: AsyncSession,
    *,
    exclude_maneuver_id: str | None = None,
    owner_user_id: str | None = None,
) -> tuple[float, int]:
    """Sum notional of open maneuver positions (scoped to owner when set)."""
    from app.services.portfolio.user_scope import maneuvers_for_user

    if not owner_user_id:
        return 0.0, 0
    query = maneuvers_for_user(owner_user_id).where(
        Maneuver.status.in_(OPEN_EXPOSURE_STATUSES)
    )
    result = await db.execute(query)
    exposure = 0.0
    count = 0
    for maneuver in result.scalars().all():
        if exclude_maneuver_id is not None and maneuver.id == exclude_maneuver_id:
            continue
        exposure += coerce_finite_float(maneuver.position_size_usd, 0.0)
        count += 1
    return round(exposure, 2), count


async def grid_exposure(*, owner_email: str | None = None) -> tuple[float, int, int]:
    """
    Sum notional of net-long grid positions from filled levels.

    Uses actual open positions — not ``config.total_capital`` — so a flat but
    still-active grid bot does not block new trades.
    """
    from app.services.portfolio.user_scope import filter_grid_bots_for_user

    bots: dict = await cache_get(_GRID_KEY) or {}
    if owner_email:
        bots = filter_grid_bots_for_user(bots, owner_email)
    exposure = 0.0
    bots_with_positions = 0
    active_bots = 0

    for data in bots.values():
        if data.get("is_active", True):
            active_bots += 1
        summary = data.get("summary") or {}
        last_price = summary.get("last_price")
        positions = compute_open_positions(data, last_price)
        if not positions:
            continue
        bots_with_positions += 1
        exposure += sum(float(p.get("notional_usd") or 0.0) for p in positions)

    return round(exposure, 2), bots_with_positions, active_bots


async def current_exposure(
    db: AsyncSession,
    *,
    exclude_maneuver_id: str | None = None,
    owner_user_id: str | None = None,
    owner_email: str | None = None,
) -> ExposureSnapshot:
    """Aggregate deployed capital across maneuvers and grid bots."""
    maneuver_usd, open_maneuvers = await maneuver_exposure(
        db,
        exclude_maneuver_id=exclude_maneuver_id,
        owner_user_id=owner_user_id,
    )
    grid_usd, grid_bots_with_positions, active_grid_bots = await grid_exposure(
        owner_email=owner_email
    )
    return ExposureSnapshot(
        maneuver_usd=maneuver_usd,
        grid_usd=grid_usd,
        open_maneuvers=open_maneuvers,
        grid_bots_with_positions=grid_bots_with_positions,
        active_grid_bots=active_grid_bots,
    )


async def reconcile_stale_grid_exposure() -> dict[str, int | float]:
    """
    Release stale grid capital locks: active bots with zero open positions had
    their full ``total_capital`` counted as deployed. Mark them idle so UI/risk
    stay aligned with the flat book.
    """
    bots: dict = await cache_get(_GRID_KEY) or {}
    if not bots:
        return {
            "deactivated_grid_bots": 0,
            "released_capital_usd": 0.0,
            "reconciled_at": datetime.now(timezone.utc).isoformat(),
        }

    deactivated = 0
    released = 0.0
    changed = False

    for bot_id, data in bots.items():
        if not data.get("is_active", True):
            continue
        summary = data.get("summary") or {}
        last_price = summary.get("last_price")
        positions = compute_open_positions(data, last_price)
        if positions:
            continue

        cfg = data.get("config") or {}
        stale_capital = float(cfg.get("total_capital") or 0.0)
        data["is_active"] = False
        bots[bot_id] = data
        deactivated += 1
        released += stale_capital
        changed = True
        logger.info(
            "Grid bot deactivated during balance reconcile (flat book)",
            bot_id=bot_id,
            released_capital=round(stale_capital, 2),
        )

    if changed:
        await cache_set(_GRID_KEY, bots, ttl=_GRID_TTL)

    return {
        "deactivated_grid_bots": deactivated,
        "released_capital_usd": round(released, 2),
        "reconciled_at": datetime.now(timezone.utc).isoformat(),
    }
