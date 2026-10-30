"""
Grid Bot Engine.
Places buy and sell orders at fixed price intervals within a defined range.
Supports arithmetic and geometric grids, auto-rebalancing, and profit tracking.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.core.logging import get_logger
from app.services.grid.config import GridType
from app.services.grid.levels import compute_grid_prices, grid_interval_at_price

logger = get_logger(__name__)


@dataclass
class GridLevel:
    price: float
    side: str           # "buy" | "sell"
    quantity: float
    order_id: Optional[str] = None
    status: str = "pending"   # pending | filled | cancelled | closed
    filled_at: Optional[datetime] = None
    fill_price: Optional[float] = None
    pnl: float = 0.0
    barrier_id: Optional[str] = None
    barrier_status: str = "active"  # active | tp | sl | time | closed


@dataclass
class GridConfig:
    ticker: str
    lower_price: float
    upper_price: float
    grid_count: int         # number of intervals
    total_capital: float    # USD allocated to this grid
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    mode: str = "paper"
    grid_type: str = GridType.GEOMETRIC.value
    trailing_enabled: bool = False
    trailing_offset_pct: float = 0.02

    def __post_init__(self) -> None:
        if self.lower_price >= self.upper_price:
            raise ValueError("lower_price must be less than upper_price")
        if self.grid_count < 2:
            raise ValueError("grid_count must be >= 2")

    @property
    def interval(self) -> float:
        mid = (self.lower_price + self.upper_price) / 2.0
        return grid_interval_at_price(
            self.lower_price, self.upper_price, self.grid_count, self.grid_type, mid
        )

    @property
    def capital_per_level(self) -> float:
        return self.total_capital / self.grid_count


@dataclass
class GridState:
    config: GridConfig
    levels: list[GridLevel] = field(default_factory=list)
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_trades: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_price: Optional[float] = None
    is_active: bool = True


class GridBotEngine:
    """
    Grid trading bot.

    Strategy:
    - Divide price range [lower, upper] into N intervals (arithmetic or geometric).
    - Place BUY orders below current price (lower levels).
    - Place SELL orders above current price (upper levels).
    - When a BUY fills, place a SELL at the next level up.
    - When a SELL fills, place a BUY at the next level down.
    - Profit = grid step * quantity per trade.
    """

    def __init__(self, config: GridConfig) -> None:
        self.config = config
        self.state = GridState(config=config)
        logger.info(
            "Grid bot created",
            ticker=config.ticker,
            range=f"{config.lower_price:.2f}–{config.upper_price:.2f}",
            levels=config.grid_count,
            grid_type=config.grid_type,
            capital=config.total_capital,
        )

    def _grid_prices(self) -> list[float]:
        return compute_grid_prices(
            self.config.lower_price,
            self.config.upper_price,
            self.config.grid_count,
            self.config.grid_type,
        )

    def _next_level_up(self, price: float) -> Optional[float]:
        prices = self._grid_prices()
        for p in prices:
            if p > price + 1e-9:
                return p
        return None

    def _next_level_down(self, price: float) -> Optional[float]:
        prices = self._grid_prices()
        for p in reversed(prices):
            if p < price - 1e-9:
                return p
        return None

    def initialize_levels(self, current_price: float) -> list[GridLevel]:
        """Build all grid levels based on current price."""
        cfg = self.config
        levels: list[GridLevel] = []
        qty_per_level = cfg.capital_per_level / current_price

        for price in self._grid_prices():
            price = round(price, 6)
            side = "buy" if price < current_price else "sell"
            if abs(price - current_price) / current_price < 0.001:
                continue
            levels.append(GridLevel(price=price, side=side, quantity=round(qty_per_level, 6)))

        self.state.levels = levels
        self.state.last_price = current_price
        logger.info(
            "Grid levels initialized",
            ticker=cfg.ticker,
            current_price=current_price,
            grid_type=cfg.grid_type,
            buy_levels=sum(1 for l in levels if l.side == "buy"),
            sell_levels=sum(1 for l in levels if l.side == "sell"),
        )
        return levels

    def on_fill(self, filled_level: GridLevel, current_price: float) -> Optional[GridLevel]:
        """
        Called when a grid order is filled.
        Returns the new counter-order to place, or None.
        """
        filled_level.status = "filled"
        filled_level.filled_at = datetime.now(timezone.utc)
        filled_level.fill_price = current_price
        self.state.total_trades += 1

        cfg = self.config
        qty = filled_level.quantity

        if filled_level.side == "buy":
            new_price = self._next_level_up(filled_level.price)
            if new_price is not None and new_price <= cfg.upper_price:
                new_price = round(new_price, 6)
                new_level = GridLevel(price=new_price, side="sell", quantity=qty)
                self.state.levels.append(new_level)
                filled_level.pnl = -filled_level.price * qty
                logger.debug("Grid fill: BUY→place SELL", at=new_price)
                return new_level
        else:
            new_price = self._next_level_down(filled_level.price)
            if new_price is not None and new_price >= cfg.lower_price:
                new_price = round(new_price, 6)
                new_level = GridLevel(price=new_price, side="buy", quantity=qty)
                self.state.levels.append(new_level)
                step = abs(filled_level.price - new_price)
                pnl = step * qty
                self.state.realized_pnl += pnl
                filled_level.pnl = pnl
                logger.debug("Grid fill: SELL→place BUY", at=new_price, pnl=pnl)
                return new_level

        return None

    def update_unrealized_pnl(self, current_price: float) -> float:
        """Update unrealized PnL based on current price."""
        self.state.last_price = current_price

        if self.config.stop_loss and current_price <= self.config.stop_loss:
            logger.warning(
                "Grid bot stop loss hit",
                ticker=self.config.ticker,
                price=current_price,
                stop=self.config.stop_loss,
            )
            self.state.is_active = False

        if self.config.take_profit and current_price >= self.config.take_profit:
            logger.info(
                "Grid bot take profit hit",
                ticker=self.config.ticker,
                price=current_price,
                tp=self.config.take_profit,
            )
            self.state.is_active = False

        filled_buys = [l for l in self.state.levels if l.side == "buy" and l.status == "filled"]
        self.state.unrealized_pnl = sum(
            (current_price - l.fill_price) * l.quantity
            for l in filled_buys
            if l.fill_price is not None
        )
        return self.state.unrealized_pnl

    def get_pending_orders(self) -> list[GridLevel]:
        """Return all levels that need to be submitted to the broker."""
        return [l for l in self.state.levels if l.status == "pending"]

    def get_summary(self) -> dict:
        """Return a summary of the grid state."""
        return {
            "ticker": self.config.ticker,
            "range": f"{self.config.lower_price:.2f}–{self.config.upper_price:.2f}",
            "grid_count": self.config.grid_count,
            "grid_type": self.config.grid_type,
            "total_capital": self.config.total_capital,
            "is_active": self.state.is_active,
            "total_trades": self.state.total_trades,
            "realized_pnl": round(self.state.realized_pnl, 4),
            "unrealized_pnl": round(self.state.unrealized_pnl, 4),
            "total_pnl": round(self.state.realized_pnl + self.state.unrealized_pnl, 4),
            "last_price": self.state.last_price,
            "pending_orders": len(self.get_pending_orders()),
            "filled_orders": sum(1 for l in self.state.levels if l.status == "filled"),
        }


def build_grid_maneuver(
    ticker: str,
    current_price: float,
    atr: float,
    capital: float = 10_000.0,
    grid_count: int = 10,
    *,
    grid_type: str = GridType.GEOMETRIC.value,
) -> GridConfig:
    """
    Auto-configure a grid bot from current price and ATR.
    Range = current_price ± 3 * ATR
    """
    spread = atr * 3
    lower = round(max(current_price - spread, current_price * 0.85), 4)
    upper = round(min(current_price + spread, current_price * 1.15), 4)
    return GridConfig(
        ticker=ticker,
        lower_price=lower,
        upper_price=upper,
        grid_count=grid_count,
        total_capital=capital,
        stop_loss=lower * 0.97,
        take_profit=upper * 1.03,
        grid_type=grid_type,
    )
