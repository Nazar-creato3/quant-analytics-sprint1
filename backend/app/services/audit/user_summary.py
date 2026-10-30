"""User-level audit summary (non-technical)."""
from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Maneuver, ManeuverStatus
from app.services.audit.types import ClosedTradeRecord
from app.services.portfolio.user_scope import maneuvers_for_user
from app.utils.audit import AuditAction


def build_user_summary(
    trades: list[ClosedTradeRecord],
    *,
    most_common_maneuver: str | None = None,
) -> dict[str, Any]:
    """Simple personal summary per spec section 3."""
    if not trades:
        return {}

    total_pnl = sum(t.realized_pnl for t in trades)
    invested = sum(t.position_size_usd for t in trades)
    wins = sum(1 for t in trades if t.realized_pnl > 0)
    win_rate = wins / len(trades)

    ticker_pnl: dict[str, float] = {}
    for t in trades:
        ticker_pnl[t.ticker] = ticker_pnl.get(t.ticker, 0.0) + t.realized_pnl
    top_tickers = sorted(ticker_pnl.items(), key=lambda kv: kv[1], reverse=True)[:3]

    capital_return_pct = (total_pnl / invested * 100.0) if invested > 0 else 0.0

    return {
        "total_pnl_usd": round(total_pnl, 2),
        "total_pnl_pct": round(capital_return_pct, 2),
        "win_rate": round(win_rate, 4),
        "top_tickers": [
            {"ticker": ticker, "pnl_usd": round(pnl, 2)} for ticker, pnl in top_tickers
        ],
        "capital_return_pct": round(capital_return_pct, 2),
        "most_common_maneuver": most_common_maneuver or "unknown",
        "trade_count": len(trades),
    }


async def resolve_most_common_maneuver(db: AsyncSession, user_id: str) -> str | None:
    """Most frequent approved maneuver strategy from audit logs."""
    result = await db.execute(
        select(AuditLog.details)
        .where(
            AuditLog.user_id == user_id,
            AuditLog.action.in_(
                (AuditAction.MANEUVER_APPROVE, AuditAction.MANEUVER_REJECT),
            ),
        )
        .order_by(AuditLog.timestamp.desc())
        .limit(500)
    )
    strategies: Counter[str] = Counter()
    for (details,) in result.all():
        if not isinstance(details, dict):
            continue
        strategy = details.get("strategy_type") or details.get("strategy")
        if strategy:
            strategies[str(strategy)] += 1

    if not strategies:
        maneuver_result = await db.execute(
            maneuvers_for_user(user_id).where(
                Maneuver.status == ManeuverStatus.APPROVED,
            ).limit(200)
        )
        for m in maneuver_result.scalars().all():
            st = getattr(m.strategy_type, "value", m.strategy_type)
            strategies[str(st)] += 1

    if not strategies:
        return None
    return strategies.most_common(1)[0][0]
