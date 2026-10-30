"""Live maneuver signal performance metrics (spec A.7–A.8)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Maneuver, ManeuverStatus, StrategyType

logger = get_logger(__name__)


@dataclass
class LivePerformanceMetrics:
    sharpe_ratio: float | None
    win_rate: float | None
    expectancy_usd: float | None
    max_drawdown_pct: float | None
    sample_size: int
    backtest_sharpe: float | None
    backtest_win_rate: float | None
    calibration_error: float | None
    as_of: str
    label: str = "live"

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "sharpe_ratio": self.sharpe_ratio,
            "win_rate": self.win_rate,
            "expectancy_usd": self.expectancy_usd,
            "max_drawdown_pct": self.max_drawdown_pct,
            "sample_size": self.sample_size,
            "backtest_sharpe": self.backtest_sharpe,
            "backtest_win_rate": self.backtest_win_rate,
            "calibration_error": self.calibration_error,
            "as_of": self.as_of,
        }


def _compute_sharpe(returns: list[float]) -> float | None:
    if len(returns) < 5:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / max(len(returns) - 1, 1)
    std = math.sqrt(var)
    if std <= 1e-12:
        return None
    return round(mean / std * math.sqrt(252), 4)


def _max_drawdown_pct(equity_curve: list[float]) -> float | None:
    if len(equity_curve) < 2:
        return None
    peak = equity_curve[0]
    max_dd = 0.0
    for val in equity_curve:
        peak = max(peak, val)
        if peak > 0:
            dd = (peak - val) / peak * 100
            max_dd = max(max_dd, dd)
    return round(max_dd, 4)


def empty_live_performance() -> LivePerformanceMetrics:
    return LivePerformanceMetrics(
        sharpe_ratio=None,
        win_rate=None,
        expectancy_usd=None,
        max_drawdown_pct=None,
        sample_size=0,
        backtest_sharpe=None,
        backtest_win_rate=None,
        calibration_error=None,
        as_of=datetime.now(timezone.utc).isoformat(),
    )


async def compute_live_maneuver_performance(
    db: AsyncSession,
    *,
    owner_user_id: str,
    min_samples: int = 5,
) -> LivePerformanceMetrics:
    """Aggregate live (executed) maneuver outcomes — never mixed with backtest."""
    if not owner_user_id:
        return empty_live_performance()
    from app.db.models import ManeuverReport

    query = select(Maneuver).where(
        Maneuver.strategy_type != StrategyType.NO_TRADE,
        Maneuver.status.in_([ManeuverStatus.FILLED, ManeuverStatus.CANCELLED]),
        Maneuver.realized_pnl.isnot(None),
    )
    query = query.join(ManeuverReport, Maneuver.report_id == ManeuverReport.id).where(
        ManeuverReport.created_by == owner_user_id
    )

    result = await db.execute(query.order_by(Maneuver.filled_at.asc()))
    rows = result.scalars().all()

    pnls = [float(m.realized_pnl or 0) for m in rows if m.realized_pnl is not None]
    notionals = [float(m.position_size_usd or 0) for m in rows if m.position_size_usd]
    returns = [
        pnl / notional
        for pnl, notional in zip(pnls, notionals[: len(pnls)])
        if notional > 0
    ]

    wins = sum(1 for p in pnls if p > 0)
    win_rate = round(wins / len(pnls), 4) if pnls else None
    expectancy = round(sum(pnls) / len(pnls), 2) if pnls else None

    equity = []
    cumulative = 0.0
    for pnl in pnls:
        cumulative += pnl
        equity.append(cumulative)

    sharpe = _compute_sharpe(returns) if len(returns) >= min_samples else None
    max_dd = _max_drawdown_pct(equity) if len(equity) >= min_samples else None

    backtest_sharpe = None
    backtest_win_rate = None
    try:
        from app.services.track_record.service import TrackRecordService

        tr = TrackRecordService().get_public_summary().to_dict()
        if tr and tr.get("aggregate"):
            agg = tr["aggregate"]
            backtest_sharpe = agg.get("sharpe_ratio")
            backtest_win_rate = agg.get("win_rate")
    except Exception as exc:
        logger.debug("Backtest benchmark load skipped", error=str(exc))

    calibration_error = None
    try:
        from app.services.prediction_hierarchy.calibration_tracker import get_live_calibration_error

        calibration_error = get_live_calibration_error()
    except Exception:
        pass

    return LivePerformanceMetrics(
        sharpe_ratio=sharpe,
        win_rate=win_rate,
        expectancy_usd=expectancy,
        max_drawdown_pct=max_dd,
        sample_size=len(pnls),
        backtest_sharpe=backtest_sharpe,
        backtest_win_rate=backtest_win_rate,
        calibration_error=calibration_error,
        as_of=datetime.now(timezone.utc).isoformat(),
    )
