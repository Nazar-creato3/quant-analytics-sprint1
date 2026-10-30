"""Grid strategy backtesting with realistic fees, slippage, and optional liquidation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from app.services.grid.config import GridConfigModel, GridType
from app.services.grid.levels import compute_grid_prices
from app.services.terminal_platform.quant.backtest import analyze_backtest
from app.services.terminal_platform.quant.models import BacktestConfig


@dataclass
class GridBacktestResult:
    total_return: float
    sharpe: float
    max_drawdown: float
    n_trades: int
    n_grid_cycles: int
    total_fees: float
    liquidation_events: int
    equity_curve: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_return": round(self.total_return, 6),
            "sharpe": round(self.sharpe, 4),
            "max_drawdown": round(self.max_drawdown, 6),
            "n_trades": self.n_trades,
            "n_grid_cycles": self.n_grid_cycles,
            "total_fees": round(self.total_fees, 4),
            "liquidation_events": self.liquidation_events,
            "equity_curve": [round(x, 4) for x in self.equity_curve[-120:]],
            "metadata": self.metadata,
        }


def run_grid_backtest(
    prices: Sequence[float],
    config: GridConfigModel,
    *,
    maintenance_margin: float = 0.05,
) -> GridBacktestResult:
    """
    Simulate grid trading bar-by-bar with fees and slippage.
    When leverage > 1, models liquidation if equity falls below maintenance margin.
    """
    price_list = [float(p) for p in prices]
    if len(price_list) < 10:
        raise ValueError("need at least 10 price bars for grid backtest")

    fee_rate = config.fee_bps / 10_000.0
    slip_rate = config.slippage_bps / 10_000.0
    cost_rate = fee_rate + slip_rate

    grid_prices = compute_grid_prices(
        config.lower_bound,
        config.upper_bound,
        config.num_levels,
        config.grid_type,
    )

    capital = float(config.capital_allocated)
    equity = capital
    equity_curve = [equity]
    period_returns: list[float] = []
    cash = capital
    inventory = 0.0
    n_trades = 0
    n_cycles = 0
    total_fees = 0.0
    liquidations = 0
    leverage = config.leverage

    # Pending orders: price -> side
    pending_buys = {p for p in grid_prices if p < price_list[0]}
    pending_sells = {p for p in grid_prices if p > price_list[0]}
    qty_per_level = capital / config.num_levels / price_list[0]

    for i in range(1, len(price_list)):
        prev_p = price_list[i - 1]
        cur_p = price_list[i]
        ret_prev = equity_curve[-1]

        # Check liquidation (leveraged futures)
        if leverage > 1.0 and inventory > 0:
            notional = inventory * cur_p
            margin_used = notional / leverage
            unrealized = (cur_p - (cash / max(inventory, 1e-12) if inventory else cur_p)) * inventory
            eq = cash + inventory * cur_p
            if eq < margin_used * maintenance_margin:
                liquidations += 1
                cash = eq * 0.1  # residual after liquidation
                inventory = 0.0
                pending_buys = {p for p in grid_prices if p < cur_p}
                pending_sells = {p for p in grid_prices if p > cur_p}
                equity = cash
                equity_curve.append(equity)
                period_returns.append(equity / ret_prev - 1.0 if ret_prev else 0.0)
                continue

        # Buy fills
        for level in sorted(pending_buys):
            if prev_p > level and cur_p <= level:
                fill_price = level * (1 + slip_rate)
                cost = fill_price * qty_per_level * (1 + fee_rate)
                if cash >= cost:
                    cash -= cost
                    inventory += qty_per_level
                    total_fees += fill_price * qty_per_level * fee_rate
                    n_trades += 1
                    pending_buys.discard(level)
                    pending_sells.add(min(p for p in grid_prices if p > level) if any(p > level for p in grid_prices) else level + (level - config.lower_bound) / config.num_levels)

        # Sell fills
        for level in sorted(pending_sells, reverse=True):
            if prev_p < level and cur_p >= level and inventory >= qty_per_level * 0.99:
                fill_price = level * (1 - slip_rate)
                proceeds = fill_price * qty_per_level * (1 - fee_rate)
                cash += proceeds
                inventory -= qty_per_level
                total_fees += fill_price * qty_per_level * fee_rate
                n_trades += 1
                n_cycles += 1
                pending_sells.discard(level)
                pending_buys.add(max(p for p in grid_prices if p < level) if any(p < level for p in grid_prices) else level - (config.upper_bound - level) / config.num_levels)

        equity = cash + inventory * cur_p
        equity_curve.append(equity)
        period_returns.append(equity / ret_prev - 1.0 if ret_prev else 0.0)

    bt_cfg = BacktestConfig(initial_capital=capital)
    analyzed = analyze_backtest(equity_curve, period_returns, n_trades=n_trades, config=bt_cfg)

    return GridBacktestResult(
        total_return=analyzed.total_return,
        sharpe=analyzed.sharpe,
        max_drawdown=analyzed.max_drawdown,
        n_trades=n_trades,
        n_grid_cycles=n_cycles,
        total_fees=total_fees,
        liquidation_events=liquidations,
        equity_curve=equity_curve,
        metadata={
            "grid_type": config.grid_type.value,
            "num_levels": config.num_levels,
            "fee_bps": config.fee_bps,
            "slippage_bps": config.slippage_bps,
            "leverage": config.leverage,
        },
    )
