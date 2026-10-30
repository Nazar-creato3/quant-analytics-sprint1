"""Live paper equity adjustments — same P&L math as open-position enrichment."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Maneuver, ManeuverReport, ManeuverStatus
from app.services.grid.execution import compute_open_positions
from app.services.portfolio.exposure import OPEN_EXPOSURE_STATUSES, _GRID_KEY
from app.services.portfolio.position_analytics import latest_prices, unrealized_net_pnl
from app.services.portfolio.user_scope import filter_grid_bots_for_user, maneuvers_for_user
from app.utils.cache import cache_get
from app.utils.json_safe import coerce_finite_float, finite_float


@dataclass(frozen=True)
class LivePnlSnapshot:
    """Unrealized + realized components aligned with maneuvers list enrichment."""

    deployed_notional_usd: float
    unrealized_maneuver_usd: float
    unrealized_grid_usd: float
    realized_closed_usd: float

    @property
    def unrealized_total_usd(self) -> float:
        return round(self.unrealized_maneuver_usd + self.unrealized_grid_usd, 2)

    @property
    def live_pnl_usd(self) -> float:
        return round(self.realized_closed_usd + self.unrealized_total_usd, 2)


async def _open_maneuvers(
    db: AsyncSession,
    *,
    owner_user_id: str | None,
) -> list[Maneuver]:
    if not owner_user_id:
        return []
    stmt = maneuvers_for_user(owner_user_id).where(
        Maneuver.status.in_(OPEN_EXPOSURE_STATUSES)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _realized_closed_pnl(
    db: AsyncSession,
    *,
    owner_user_id: str | None,
) -> float:
    if not owner_user_id:
        return 0.0
    stmt = (
        select(func.coalesce(func.sum(Maneuver.realized_pnl), 0.0))
        .select_from(Maneuver)
        .join(ManeuverReport, Maneuver.report_id == ManeuverReport.id)
        .where(
            ManeuverReport.created_by == owner_user_id,
            Maneuver.status == ManeuverStatus.CLOSED,
        )
    )
    result = await db.execute(stmt)
    return round(float(result.scalar_one() or 0.0), 2)


async def _grid_unrealized(
    *,
    owner_email: str | None,
    prices: dict[str, float],
) -> float:
    bots: dict = await cache_get(_GRID_KEY) or {}
    if owner_email:
        bots = filter_grid_bots_for_user(bots, owner_email)

    unrealized = 0.0
    for data in bots.values():
        cfg = data.get("config") or {}
        ticker = str(cfg.get("ticker") or "").upper()
        summary = data.get("summary") or {}
        mark = prices.get(ticker) or finite_float(summary.get("last_price"))
        for pos in compute_open_positions(data, mark):
            unrealized += float(pos.get("unrealized_pnl") or 0.0)
    return round(unrealized, 2)


async def compute_live_pnl(
    db: AsyncSession,
    *,
    owner_user_id: str | None,
    owner_email: str | None,
    price_overrides: dict[str, float] | None = None,
) -> LivePnlSnapshot:
    """
    Aggregate realized (closed maneuvers) and unrealized (open maneuvers + grid).

    Uses ``latest_prices`` + optional overrides — the same price source as
    ``enrich_maneuvers`` on GET /maneuvers.
    """
    open_rows = await _open_maneuvers(db, owner_user_id=owner_user_id)
    tickers = [m.ticker for m in open_rows]

    bots: dict = await cache_get(_GRID_KEY) or {}
    if owner_email:
        bots = filter_grid_bots_for_user(bots, owner_email)
    for data in bots.values():
        ticker = str((data.get("config") or {}).get("ticker") or "")
        if ticker:
            tickers.append(ticker)

    prices = await latest_prices(db, tickers)
    if price_overrides:
        for ticker, px in price_overrides.items():
            if px is not None and px > 0:
                prices[ticker.upper()] = float(px)

    deployed = 0.0
    unrealized_m = 0.0
    for m in open_rows:
        deployed += coerce_finite_float(m.position_size_usd, 0.0)
        px = prices.get(m.ticker.upper())
        pnl = unrealized_net_pnl(m, finite_float(px))
        if pnl is not None:
            unrealized_m += pnl

    unrealized_g = await _grid_unrealized(owner_email=owner_email, prices=prices)
    realized = await _realized_closed_pnl(db, owner_user_id=owner_user_id)

    return LivePnlSnapshot(
        deployed_notional_usd=round(deployed, 2),
        unrealized_maneuver_usd=round(unrealized_m, 2),
        unrealized_grid_usd=unrealized_g,
        realized_closed_usd=realized,
    )
