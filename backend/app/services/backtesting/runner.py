"""
CLI entry point for running backtests.

Usage:
    python -m app.services.backtesting.runner --ticker AAPL --start 2023-01-01 --end 2024-01-01
    python -m app.services.backtesting.runner --strategy momentum_ml --ticker SPY --start 2022-01-01 --end 2023-12-31
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.services.backtesting.engine import Backtester

logger = get_logger(__name__)


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


async def _fetch_data(ticker: str, start: datetime, end: datetime):
    import pandas as pd
    from app.services.market_data.client import get_market_data_client

    client = get_market_data_client()
    bars = await client.get_bars(ticker, "1d", start, end)
    if not bars:
        raise RuntimeError(f"No market data for {ticker}")
    df = pd.DataFrame(bars)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df.columns = [c.lower() for c in df.columns]
    return df


async def _run_backtest(args: argparse.Namespace) -> dict:
    df = await _fetch_data(args.ticker.upper(), _parse_date(args.start), _parse_date(args.end))
    bt = Backtester(
        strategy=args.strategy,
        initial_capital=args.capital or settings.DEFAULT_PORTFOLIO_SIZE,
        risk_pct=args.risk_pct,
        parameters=json.loads(args.params) if args.params else {},
    )
    result = bt.run(df, args.ticker.upper())
    return result.to_dict()


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Run a strategy backtest")
    parser.add_argument("--strategy", default="momentum_ml", choices=["momentum_ml", "mean_reversion", "grid"])
    parser.add_argument("--ticker", required=True, help="Ticker symbol, e.g. AAPL")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--capital", type=float, default=None, help="Initial capital USD")
    parser.add_argument("--risk-pct", type=float, default=2.0, help="Max risk per trade %%")
    parser.add_argument("--params", default=None, help='JSON parameters, e.g. \'{"lookback": 20}\'')
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    try:
        result = asyncio.run(_run_backtest(args))
    except Exception as exc:
        logger.error("Backtest failed", error=str(exc))
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"\nBacktest: {args.strategy} / {args.ticker}")
        print(f"Period: {args.start} → {args.end}")
        print(f"Return: {result.get('total_return_pct', 0):.2f}%")
        metrics = result.get("metrics", {})
        print(f"Sharpe: {metrics.get('sharpe_ratio', 0):.2f}")
        print(f"Max DD: {metrics.get('max_drawdown_pct', 0):.2f}%")
        print(f"Trades: {metrics.get('total_trades', 0)} | Win rate: {metrics.get('win_rate', 0):.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
