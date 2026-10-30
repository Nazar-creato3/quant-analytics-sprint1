"""
Backtest Celery task.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from typing import Any
from app.tasks.celery_app import celery_app
from app.core.logging import get_logger

logger = get_logger(__name__)


def failed_backtest_metrics() -> dict[str, Any]:
    """Metrics stored on a failed run — no exception text (GA16-267)."""
    return {"failed": True}


@celery_app.task(
    bind=True,
    name="app.tasks.backtest.run_backtest_task",
    max_retries=1,
)
def run_backtest_task(self, run_id: str) -> dict[str, Any]:
    """Run a backtest and save results to DB."""
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(_async_backtest(run_id))
        return result
    finally:
        loop.close()


async def _async_backtest(run_id: str) -> dict[str, Any]:
    import pandas as pd
    from sqlalchemy import select
    from app.db.models import BacktestRun
    from app.db.session import AsyncSessionLocal
    from app.services.backtesting.engine import Backtester
    from app.services.backtest_analysis.classifier import classify_trade_log
    from app.services.market_data.client import get_market_data_client

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(BacktestRun).where(BacktestRun.id == run_id))
        run = result.scalar_one_or_none()
        if not run:
            raise ValueError(f"BacktestRun {run_id} not found")

        run.status = "running"
        await session.commit()

        try:
            client = get_market_data_client()
            bars = await client.get_bars(
                run.ticker, "1d", run.start_date, run.end_date
            )
            if not bars:
                raise ValueError(f"No market data for {run.ticker}")

            df = pd.DataFrame(bars)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df.set_index("timestamp").sort_index()
            df.columns = [c.lower() for c in df.columns]

            backtester = Backtester(
                strategy=run.strategy,
                initial_capital=run.initial_capital,
                parameters=run.parameters,
            )
            bt_result = backtester.run(df, run.ticker)

            run.final_capital = bt_result.final_capital
            run.total_return_pct = bt_result.total_return_pct
            run.sharpe_ratio = bt_result.metrics.get("sharpe_ratio")
            run.max_drawdown_pct = bt_result.metrics.get("max_drawdown_pct")
            run.total_trades = bt_result.metrics.get("total_trades", 0)
            run.win_rate = bt_result.metrics.get("win_rate")
            run.equity_curve = bt_result.equity_curve
            run.trade_log = classify_trade_log([
                {
                    "entry_date": t.entry_date.isoformat() if hasattr(t.entry_date, "isoformat") else str(t.entry_date),
                    "exit_date": t.exit_date.isoformat() if t.exit_date and hasattr(t.exit_date, "isoformat") else str(t.exit_date) if t.exit_date else None,
                    "direction": t.direction,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "pnl": round(t.pnl, 4),
                    "exit_reason": t.exit_reason,
                }
                for t in bt_result.trades
            ])
            from app.services.backtest_analysis.classifier import filter_clean_trades
            clean_trades = filter_clean_trades(run.trade_log)
            run.metrics = {
                **bt_result.metrics,
                "clean_trade_count": len(clean_trades),
                "non_clean_trade_count": len(run.trade_log) - len(clean_trades),
            }
            run.status = "complete"
            run.completed_at = datetime.now(timezone.utc)
            await session.commit()

            logger.info(
                "Backtest complete",
                run_id=run_id,
                ticker=run.ticker,
                strategy=run.strategy,
                total_return=bt_result.total_return_pct,
                sharpe=bt_result.metrics.get("sharpe_ratio"),
            )
            return {"run_id": run_id, "status": "complete", "return_pct": bt_result.total_return_pct}

        except Exception as exc:
            run.status = "failed"
            run.metrics = failed_backtest_metrics()
            await session.commit()
            logger.error("Backtest failed", run_id=run_id, error=str(exc), exc_info=True)
            raise
