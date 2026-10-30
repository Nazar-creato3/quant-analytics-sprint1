"""Terminal portfolio summary block — reuses portfolio metrics / live equity."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.terminal_platform.market.schemas import (
    PortfolioPositionRow,
    PortfolioSummaryBlock,
)

logger = get_logger(__name__)


async def build_portfolio_summary(
    db: Optional[AsyncSession] = None,
    email: Optional[str] = None,
) -> PortfolioSummaryBlock:
    """
    Honest empty when no user / no positions.
    When authenticated, reuse Dashboard portfolio metrics + exposure snapshot.
    """
    if not email or db is None:
        return PortfolioSummaryBlock(
            has_positions=False,
            message="нет данных",
            open_positions=0,
        )

    try:
        from app.services.portfolio.exposure import current_exposure
        from app.services.portfolio.metrics import build_portfolio_metrics
        from app.services.portfolio.user_scope import get_user_by_email
    except Exception as exc:
        logger.warning("portfolio imports failed", error=str(exc))
        return PortfolioSummaryBlock(
            has_positions=False,
            message="нет данных",
        )

    try:
        metrics = await build_portfolio_metrics(email, db)
        user = await get_user_by_email(db, email)
        owner_user_id = user.id if user else None
        snap = await current_exposure(
            db,
            owner_user_id=owner_user_id,
            owner_email=email,
        )

        open_count = int(getattr(snap, "open_maneuvers", 0) or 0) + int(
            getattr(snap, "active_grid_bots", 0) or 0
        )
        has = open_count > 0 or float(metrics.trading_usd or 0) > 0

        # Concentration: largest single position share if we can list maneuvers
        positions: list[PortfolioPositionRow] = []
        concentration = None
        try:
            from app.db.models import Maneuver
            from app.services.portfolio.exposure import OPEN_EXPOSURE_STATUSES
            from app.services.portfolio.user_scope import maneuvers_for_user
            from sqlalchemy import select

            if owner_user_id:
                stmt = maneuvers_for_user(owner_user_id).where(
                    Maneuver.status.in_(OPEN_EXPOSURE_STATUSES)
                )
            else:
                stmt = select(Maneuver).where(Maneuver.status.in_(OPEN_EXPOSURE_STATUSES)).limit(0)
            result = await db.execute(stmt)
            rows = list(result.scalars().all())
            total_mv = 0.0
            tmp: list[tuple[str, float, float]] = []
            for m in rows:
                sym = str(getattr(m, "ticker", None) or getattr(m, "symbol", "") or "").upper()
                notional = float(getattr(m, "notional_usd", None) or getattr(m, "size_usd", 0) or 0)
                upnl = float(getattr(m, "unrealized_pnl", None) or 0)
                if not sym:
                    continue
                mv = abs(notional)
                total_mv += mv
                tmp.append((sym, mv, upnl))
            if total_mv > 0:
                for sym, mv, upnl in tmp:
                    positions.append(
                        PortfolioPositionRow(
                            symbol=sym,
                            market_value=round(mv, 2),
                            unrealized_pnl=round(upnl, 2),
                            weight_pct=round(mv / total_mv * 100.0, 2),
                        )
                    )
                concentration = max((p.weight_pct or 0) for p in positions) if positions else None
        except Exception as exc:
            logger.debug("position list skipped", error=str(exc))

        if not has:
            return PortfolioSummaryBlock(
                has_positions=False,
                message="No open positions — capital fully in cash / buffer",
                total_usd=metrics.total_usd,
                trading_usd=metrics.trading_usd,
                balance_usd=metrics.balance_usd,
                unrealized_pnl_usd=metrics.unrealized_pnl_usd,
                realized_pnl_usd=metrics.realized_pnl_usd,
                exposure_pct=metrics.exposure_pct,
                open_positions=0,
                mode=metrics.mode,
                source=metrics.source,
                as_of=metrics.as_of,
            )

        return PortfolioSummaryBlock(
            has_positions=True,
            total_usd=metrics.total_usd,
            trading_usd=metrics.trading_usd,
            balance_usd=metrics.balance_usd,
            total_pnl_usd=round(
                float(metrics.unrealized_pnl_usd or 0) + float(metrics.realized_pnl_usd or 0),
                2,
            ),
            unrealized_pnl_usd=metrics.unrealized_pnl_usd,
            realized_pnl_usd=metrics.realized_pnl_usd,
            exposure_pct=metrics.exposure_pct,
            concentration_pct=concentration,
            open_positions=open_count,
            positions=positions[:25],
            mode=metrics.mode,
            source=metrics.source,
            as_of=metrics.as_of,
        )
    except Exception as exc:
        logger.warning("portfolio summary failed", error=str(exc))
        return PortfolioSummaryBlock(
            has_positions=False,
            message="нет данных",
            open_positions=0,
        )
