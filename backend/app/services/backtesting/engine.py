"""
Vectorized backtesting engine.
Supports momentum_ml, mean_reversion, and grid strategies.
Returns: equity curve, trade log, and Sharpe/Drawdown/Win-rate metrics.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from app.core.logging import get_logger
from app.services.ml.features import compute_features

logger = get_logger(__name__)


@dataclass
class BacktestTrade:
    entry_date: datetime
    exit_date: Optional[datetime]
    ticker: str
    direction: str
    entry_price: float
    exit_price: Optional[float]
    quantity: float
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""

    @property
    def is_open(self) -> bool:
        return self.exit_date is None


from typing import Optional


@dataclass
class BacktestResult:
    strategy: str
    ticker: str
    initial_capital: float
    final_capital: float
    equity_curve: list[dict]
    trades: list[BacktestTrade]
    metrics: dict[str, float]

    @property
    def total_return_pct(self) -> float:
        return (self.final_capital / self.initial_capital - 1) * 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "ticker": self.ticker,
            "initial_capital": self.initial_capital,
            "final_capital": round(self.final_capital, 2),
            "total_return_pct": round(self.total_return_pct, 4),
            "metrics": self.metrics,
            "equity_curve": self.equity_curve,
            "trades": [
                {
                    "entry_date": t.entry_date.isoformat(),
                    "exit_date": t.exit_date.isoformat() if t.exit_date else None,
                    "direction": t.direction,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "quantity": t.quantity,
                    "pnl": round(t.pnl, 4),
                    "pnl_pct": round(t.pnl_pct, 4),
                    "exit_reason": t.exit_reason,
                }
                for t in self.trades
            ],
        }


class Backtester:
    """
    Event-driven vectorized backtester.

    Execution assumptions:
    - Entry/exit at next bar's open (realistic fill simulation)
    - 0.1% slippage per trade
    - $1 per trade commission
    - No margin / no shorting margin requirements
    """

    SLIPPAGE = 0.001   # 0.1%
    COMMISSION = 1.0   # USD per trade

    def __init__(
        self,
        strategy: str,
        initial_capital: float = 100_000.0,
        risk_pct: float = 2.0,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.risk_pct = risk_pct
        self.params = parameters or {}

    def run(self, df: pd.DataFrame, ticker: str) -> BacktestResult:
        """
        Run backtest on OHLCV DataFrame.
        Dispatches to strategy-specific runner.
        """
        if len(df) < 50:
            raise ValueError(f"Need at least 50 bars, got {len(df)}")

        df = compute_features(df.copy())
        df = df.dropna(subset=["close", "sma_20", "rsi_14", "atr_14"])

        if self.strategy == "momentum_ml":
            return self._run_momentum(df, ticker)
        elif self.strategy == "mean_reversion":
            return self._run_mean_reversion(df, ticker)
        elif self.strategy == "grid":
            return self._run_grid(df, ticker)
        else:
            raise ValueError(f"Unknown strategy: {self.strategy!r}")

    def _run_momentum(self, df: pd.DataFrame, ticker: str) -> BacktestResult:
        """
        Momentum strategy:
        - Enter LONG when: RSI crosses above 40, MACD bullish, price > SMA20, volume spike.
        - Exit when: RSI > 70 OR price < SMA20 OR stop loss hit.
        """
        capital = self.initial_capital
        equity_curve = []
        trades: list[BacktestTrade] = []
        position: BacktestTrade | None = None

        for i in range(1, len(df)):
            bar = df.iloc[i]
            prev = df.iloc[i - 1]
            ts = bar.name if isinstance(bar.name, datetime) else datetime.fromisoformat(str(bar.name))

            price = float(bar["close"])
            atr = float(bar["atr_14"])

            if position is None:
                # Entry signal
                rsi_cross = float(prev["rsi_14"]) < 40 and float(bar["rsi_14"]) >= 40
                macd_bull = float(bar["macd_bullish"]) == 1
                above_sma = price > float(bar["sma_20"])
                vol_spike = float(bar["volume_ratio"]) > 1.2

                if rsi_cross and macd_bull and above_sma and vol_spike:
                    entry_price = price * (1 + self.SLIPPAGE)
                    stop = entry_price - atr * 2
                    risk_usd = capital * (self.risk_pct / 100)
                    qty = risk_usd / (entry_price - stop) if (entry_price - stop) > 0 else 0
                    position_usd = qty * entry_price
                    if position_usd > capital * 0.8:
                        qty = (capital * 0.8) / entry_price

                    capital -= qty * entry_price + self.COMMISSION
                    position = BacktestTrade(
                        entry_date=ts, exit_date=None, ticker=ticker,
                        direction="long", entry_price=entry_price,
                        exit_price=None, quantity=qty,
                    )
            else:
                # Exit signal
                stop = position.entry_price - atr * 2
                rsi_exit = float(bar["rsi_14"]) > 70
                sma_exit = price < float(bar["sma_20"])
                stop_hit = price <= stop

                if rsi_exit or sma_exit or stop_hit:
                    exit_price = price * (1 - self.SLIPPAGE)
                    capital += position.quantity * exit_price - self.COMMISSION
                    pnl = (exit_price - position.entry_price) * position.quantity - self.COMMISSION * 2
                    pnl_pct = (exit_price - position.entry_price) / position.entry_price * 100
                    reason = "rsi_overbought" if rsi_exit else ("below_sma" if sma_exit else "stop_loss")

                    position.exit_date = ts
                    position.exit_price = exit_price
                    position.pnl = pnl
                    position.pnl_pct = pnl_pct
                    position.exit_reason = reason
                    trades.append(position)
                    position = None

            # Mark-to-market equity
            mtm = capital + (position.quantity * price if position else 0)
            equity_curve.append({"date": ts.isoformat() if hasattr(ts, "isoformat") else str(ts), "equity": round(mtm, 2)})

        # Close any open position at last bar
        if position:
            last_price = float(df.iloc[-1]["close"])
            pnl = (last_price - position.entry_price) * position.quantity
            position.exit_date = df.index[-1]
            position.exit_price = last_price
            position.pnl = pnl
            position.pnl_pct = pnl / (position.entry_price * position.quantity) * 100
            position.exit_reason = "end_of_data"
            trades.append(position)
            capital += position.quantity * last_price

        return BacktestResult(
            strategy=self.strategy,
            ticker=ticker,
            initial_capital=self.initial_capital,
            final_capital=capital,
            equity_curve=equity_curve,
            trades=trades,
            metrics=self._compute_metrics(equity_curve, trades),
        )

    def _run_mean_reversion(self, df: pd.DataFrame, ticker: str) -> BacktestResult:
        """
        Mean reversion strategy:
        - Enter LONG when price touches lower Bollinger Band + RSI < 35.
        - Exit when price returns to mid BB OR RSI > 60.
        """
        capital = self.initial_capital
        equity_curve = []
        trades: list[BacktestTrade] = []
        position: BacktestTrade | None = None

        for i in range(1, len(df)):
            bar = df.iloc[i]
            price = float(bar["close"])
            ts = bar.name

            if position is None:
                at_lower_bb = price <= float(bar["bb_lower"]) * 1.005
                rsi_low = float(bar["rsi_14"]) < 35
                if at_lower_bb and rsi_low:
                    entry_price = price * (1 + self.SLIPPAGE)
                    qty = (capital * 0.15) / entry_price  # 15% per trade
                    capital -= qty * entry_price + self.COMMISSION
                    position = BacktestTrade(
                        entry_date=ts, exit_date=None, ticker=ticker,
                        direction="long", entry_price=entry_price,
                        exit_price=None, quantity=qty,
                    )
            else:
                at_mid_bb = price >= float(bar["bb_mid"])
                rsi_high = float(bar["rsi_14"]) > 60
                stop_hit = price < float(bar["bb_lower"]) * 0.97

                if at_mid_bb or rsi_high or stop_hit:
                    exit_price = price * (1 - self.SLIPPAGE)
                    pnl = (exit_price - position.entry_price) * position.quantity - self.COMMISSION * 2
                    capital += position.quantity * exit_price - self.COMMISSION
                    position.exit_date = ts
                    position.exit_price = exit_price
                    position.pnl = pnl
                    position.pnl_pct = (exit_price - position.entry_price) / position.entry_price * 100
                    position.exit_reason = "mid_bb" if at_mid_bb else ("rsi_exit" if rsi_high else "stop")
                    trades.append(position)
                    position = None

            mtm = capital + (position.quantity * price if position else 0)
            equity_curve.append({"date": str(ts), "equity": round(mtm, 2)})

        return BacktestResult(
            strategy=self.strategy,
            ticker=ticker,
            initial_capital=self.initial_capital,
            final_capital=capital,
            equity_curve=equity_curve,
            trades=trades,
            metrics=self._compute_metrics(equity_curve, trades),
        )

    def _run_grid(self, df: pd.DataFrame, ticker: str) -> BacktestResult:
        """
        Grid strategy backtest: simulate fills when price crosses grid levels.
        """
        from app.services.grid.engine import GridBotEngine, build_grid_maneuver

        capital = self.initial_capital
        equity_curve = []
        trades: list[BacktestTrade] = []

        first_price = float(df.iloc[0]["close"])
        first_atr = float(df.iloc[0].get("atr_14", first_price * 0.02))
        grid_capital = capital * 0.5  # allocate 50% to grid

        cfg = build_grid_maneuver(
            ticker=ticker,
            current_price=first_price,
            atr=first_atr,
            capital=grid_capital,
            grid_count=self.params.get("grid_count", 10),
        )
        bot = GridBotEngine(cfg)
        bot.initialize_levels(first_price)
        prev_price = first_price

        for i in range(1, len(df)):
            bar = df.iloc[i]
            price = float(bar["close"])
            ts = bar.name

            # Check if any grid level was crossed
            for level in bot.get_pending_orders():
                if level.side == "buy" and prev_price > level.price >= price:
                    level.status = "filled"
                    level.filled_at = ts
                    level.fill_price = level.price
                    new_level = bot.on_fill(level, price)
                    capital -= level.price * level.quantity + self.COMMISSION

                elif level.side == "sell" and prev_price < level.price <= price:
                    level.status = "filled"
                    level.filled_at = ts
                    level.fill_price = level.price
                    new_level = bot.on_fill(level, price)
                    capital += level.price * level.quantity - self.COMMISSION

            bot.update_unrealized_pnl(price)
            mtm = capital + bot.state.realized_pnl + bot.state.unrealized_pnl
            equity_curve.append({"date": str(ts), "equity": round(mtm, 2)})
            prev_price = price

        final_capital = capital + bot.state.realized_pnl + bot.state.unrealized_pnl
        return BacktestResult(
            strategy=self.strategy,
            ticker=ticker,
            initial_capital=self.initial_capital,
            final_capital=final_capital,
            equity_curve=equity_curve,
            trades=trades,
            metrics={
                **self._compute_metrics(equity_curve, trades),
                "grid_realized_pnl": round(bot.state.realized_pnl, 2),
                "grid_total_trades": bot.state.total_trades,
            },
        )

    @staticmethod
    def _compute_metrics(
        equity_curve: list[dict], trades: list[BacktestTrade]
    ) -> dict[str, float]:
        """Compute Sharpe, max drawdown, win rate, and other metrics."""
        if not equity_curve:
            return {}

        equities = np.array([e["equity"] for e in equity_curve])
        returns = np.diff(equities) / equities[:-1]
        returns = returns[~np.isnan(returns)]

        sharpe = 0.0
        if len(returns) > 1 and returns.std() > 0:
            sharpe = float(np.mean(returns) / returns.std() * np.sqrt(252))

        # Max drawdown
        peak = np.maximum.accumulate(equities)
        drawdowns = (equities - peak) / peak
        max_dd = float(np.min(drawdowns)) * 100

        # Win rate
        completed = [t for t in trades if t.exit_price is not None]
        wins = [t for t in completed if t.pnl > 0]
        win_rate = len(wins) / len(completed) if completed else 0.0

        # Average trade
        avg_pnl = float(np.mean([t.pnl for t in completed])) if completed else 0.0
        avg_win = float(np.mean([t.pnl for t in wins])) if wins else 0.0
        losses = [t for t in completed if t.pnl <= 0]
        avg_loss = float(np.mean([t.pnl for t in losses])) if losses else 0.0
        profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0

        return {
            "sharpe_ratio": round(sharpe, 4),
            "max_drawdown_pct": round(max_dd, 4),
            "win_rate": round(win_rate, 4),
            "total_trades": len(completed),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "avg_trade_pnl": round(avg_pnl, 4),
            "avg_win_pnl": round(avg_win, 4),
            "avg_loss_pnl": round(avg_loss, 4),
            "profit_factor": round(profit_factor, 4),
            "total_return_pct": round(
                (equities[-1] / equities[0] - 1) * 100 if equities[0] > 0 else 0, 4
            ),
        }
