"""
GridExecutor — state machine orchestrating grid trading, DCA hybrid, trailing grid,
triple-barrier exits, and pump/dump circuit breaker.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from app.core.logging import get_logger
from app.services.grid.circuit_breaker import PumpDumpCircuitBreaker
from app.services.grid.config import GridConfigModel, GridExecutorState
from app.services.grid.engine import GridBotEngine, GridConfig, GridLevel
from app.services.grid.levels import compute_grid_prices
from app.services.grid.triple_barrier import BarrierExit, TripleBarrierConfig, TripleBarrierPosition

logger = get_logger(__name__)


@dataclass
class DcaState:
    """DCA averaging state when price exits grid bounds."""

    active: bool = False
    direction: str = "buy"  # buy when below grid, sell when above
    entries: list[dict[str, float]] = field(default_factory=list)
    avg_entry: float = 0.0
    total_qty: float = 0.0

    def record_entry(self, price: float, qty: float) -> None:
        self.entries.append({"price": price, "qty": qty})
        self.total_qty += qty
        notional = sum(e["price"] * e["qty"] for e in self.entries)
        self.avg_entry = notional / self.total_qty if self.total_qty else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "direction": self.direction,
            "entries": self.entries,
            "avg_entry": round(self.avg_entry, 6),
            "total_qty": round(self.total_qty, 6),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DcaState:
        d = cls(
            active=bool(data.get("active", False)),
            direction=str(data.get("direction", "buy")),
            entries=list(data.get("entries") or []),
            avg_entry=float(data.get("avg_entry", 0.0)),
            total_qty=float(data.get("total_qty", 0.0)),
        )
        return d


@dataclass
class ExecutorResult:
    filled_levels: list[GridLevel] = field(default_factory=list)
    barrier_closes: list[dict[str, Any]] = field(default_factory=list)
    state_changed: bool = False
    new_state: GridExecutorState = GridExecutorState.GRID_ACTIVE
    circuit_event: dict[str, Any] | None = None
    trailing_shifted: bool = False
    dca_action: str | None = None


class GridExecutor:
    """
    Hummingbot-inspired executor pattern (reimplemented, not copied):
    - GRID_ACTIVE: manage grid orders within bounds
    - DCA_MODE: average position when price exits range
    - Triple-barrier per filled level
    - Trailing grid shifts range with uptrend
    - Circuit breaker pauses new orders on pump/dump
    """

    def __init__(self, config: GridConfigModel) -> None:
        self.config = config
        self.state = GridExecutorState.GRID_ACTIVE
        self.dca = DcaState()
        self.circuit = PumpDumpCircuitBreaker()
        self.barrier_positions: dict[str, TripleBarrierPosition] = {}
        self._engine = self._build_engine()

    def _build_engine(self) -> GridBotEngine:
        d = self.config.to_engine_dict()
        cfg = GridConfig(
            ticker=d["ticker"],
            lower_price=d["lower_price"],
            upper_price=d["upper_price"],
            grid_count=d["grid_count"],
            total_capital=d["total_capital"],
            take_profit=d.get("take_profit"),
            stop_loss=d.get("stop_loss"),
            grid_type=d.get("grid_type", "geometric"),
            trailing_enabled=d.get("trailing_enabled", False),
            trailing_offset_pct=d.get("trailing_offset_pct", 0.02),
        )
        return GridBotEngine(cfg)

    @property
    def engine(self) -> GridBotEngine:
        return self._engine

    def initialize(self, current_price: float) -> list[GridLevel]:
        return self._engine.initialize_levels(current_price)

    def _barrier_config(self) -> TripleBarrierConfig:
        return TripleBarrierConfig(
            take_profit_pct=self.config.level_take_profit_pct,
            stop_loss_pct=self.config.level_stop_loss_pct,
            max_hold_hours=self.config.level_max_hold_hours,
        )

    def _maybe_trailing_shift(self, price: float) -> bool:
        if not self.config.trailing_enabled:
            return False
        cfg = self._engine.config
        width = cfg.upper_price - cfg.lower_price
        if width <= 0:
            return False
        # Shift grid up if price exceeds upper - offset
        trigger = cfg.upper_price - width * self.config.trailing_offset_pct
        if price <= trigger:
            return False
        shift = price - trigger
        cfg.lower_price = round(cfg.lower_price + shift, 6)
        cfg.upper_price = round(cfg.upper_price + shift, 6)
        self.config.lower_bound = cfg.lower_price
        self.config.upper_bound = cfg.upper_price
        logger.info(
            "Trailing grid shifted",
            ticker=cfg.ticker,
            new_range=f"{cfg.lower_price:.2f}–{cfg.upper_price:.2f}",
        )
        return True

    def _check_state_transition(self, price: float) -> bool:
        cfg = self._engine.config
        if self.state == GridExecutorState.GRID_ACTIVE:
            if not self.config.dca_enabled:
                return False
            if price < cfg.lower_price or price > cfg.upper_price:
                self.state = GridExecutorState.DCA_MODE
                self.dca.active = True
                self.dca.direction = "buy" if price < cfg.lower_price else "sell"
                logger.info(
                    "Grid → DCA mode",
                    ticker=cfg.ticker,
                    price=price,
                    direction=self.dca.direction,
                )
                return True
        elif self.state == GridExecutorState.DCA_MODE:
            in_range = cfg.lower_price <= price <= cfg.upper_price
            tp_hit = False
            if self.dca.total_qty > 0 and self.dca.avg_entry > 0:
                if self.dca.direction == "buy":
                    tp_hit = price >= self.dca.avg_entry * (1 + self.config.dca_take_profit_pct)
                else:
                    tp_hit = price <= self.dca.avg_entry * (1 - self.config.dca_take_profit_pct)
            if in_range or tp_hit:
                self.state = GridExecutorState.GRID_ACTIVE
                self.dca = DcaState()
                logger.info("DCA → Grid mode", ticker=cfg.ticker, price=price, tp_hit=tp_hit)
                return True
        return False

    def _run_dca_tick(self, price: float, prev_price: float) -> str | None:
        if self.state != GridExecutorState.DCA_MODE or not self.dca.active:
            return None
        if not self.circuit.allows_new_orders():
            return None

        step = price * self.config.dca_step_pct
        cfg = self._engine.config
        capital_slice = cfg.capital_per_level

        if self.dca.direction == "buy" and prev_price > price and price <= prev_price - step * 0.5:
            qty = capital_slice / price
            self.dca.record_entry(price, qty)
            return f"DCA buy @ ${price:.2f}"
        if self.dca.direction == "sell" and prev_price < price and price >= prev_price + step * 0.5:
            qty = capital_slice / price
            self.dca.record_entry(price, qty)
            return f"DCA sell @ ${price:.2f}"
        return None

    def _check_barriers(self, price: float, now: datetime) -> list[dict[str, Any]]:
        closes: list[dict[str, Any]] = []
        for level_id, pos in list(self.barrier_positions.items()):
            if pos.is_closed:
                continue
            exit_reason = pos.check_barriers(price, now)
            if exit_reason == BarrierExit.NONE:
                continue
            pnl = pos.close(price, exit_reason, now)
            closes.append({
                "level_id": level_id,
                "exit_reason": exit_reason.value,
                "exit_price": price,
                "pnl": pnl,
            })
            self._engine.state.realized_pnl += pnl
            logger.debug(
                "Triple-barrier exit",
                level_id=level_id,
                reason=exit_reason.value,
                pnl=pnl,
            )
        return closes

    def _register_barrier(self, level: GridLevel, now: datetime) -> None:
        level_id = f"{level.side}-{level.price}-{uuid4().hex[:8]}"
        pos = TripleBarrierPosition(
            level_id=level_id,
            side=level.side,
            entry_price=float(level.fill_price or level.price),
            quantity=level.quantity,
            opened_at=now,
            config=self._barrier_config(),
        )
        self.barrier_positions[level_id] = pos
        level.barrier_id = level_id  # type: ignore[attr-defined]

    def on_price_tick(
        self,
        price: float,
        prev_price: float,
        *,
        now: datetime | None = None,
    ) -> ExecutorResult:
        """Process one price update through the full executor pipeline."""
        ts = now or datetime.now(timezone.utc)
        result = ExecutorResult(new_state=self.state)

        # Circuit breaker
        cb_ev = self.circuit.on_price(price, ts)
        if cb_ev:
            result.circuit_event = cb_ev.to_dict()

        # Trailing grid
        if self._maybe_trailing_shift(price):
            result.trailing_shifted = True
            prices = compute_grid_prices(
                self._engine.config.lower_price,
                self._engine.config.upper_price,
                self._engine.config.grid_count,
                self._engine.config.grid_type,
            )
            self._engine.state.levels = [
                GridLevel(price=p, side="buy" if p < price else "sell", quantity=0)
                for p in prices
                if abs(p - price) / max(price, 1e-9) >= 0.001
            ]

        # State machine
        if self._check_state_transition(price):
            result.state_changed = True
            result.new_state = self.state

        # Triple-barrier exits on open positions
        result.barrier_closes = self._check_barriers(price, ts)
        for close in result.barrier_closes:
            self._engine.state.realized_pnl += close.get("pnl", 0.0)

        # DCA mode
        dca_msg = self._run_dca_tick(price, prev_price)
        if dca_msg:
            result.dca_action = dca_msg

        # Grid fills (only in GRID_ACTIVE and if circuit allows)
        if (
            self.state == GridExecutorState.GRID_ACTIVE
            and self.circuit.allows_new_orders()
            and self._engine.state.is_active
        ):
            for level in self._engine.get_pending_orders():
                if level.side == "buy" and prev_price > level.price and price <= level.price:
                    level.fill_price = level.price
                    self._engine.on_fill(level, price)
                    self._register_barrier(level, ts)
                    result.filled_levels.append(level)
                elif level.side == "sell" and prev_price < level.price and price >= level.price:
                    level.fill_price = level.price
                    self._engine.on_fill(level, price)
                    self._register_barrier(level, ts)
                    result.filled_levels.append(level)

        self._engine.update_unrealized_pnl(price)
        result.new_state = self.state
        return result

    def restore_from_dict(self, data: dict[str, Any]) -> None:
        """Hydrate executor state from persisted bot dict."""
        self.state = GridExecutorState(data.get("executor_state", GridExecutorState.GRID_ACTIVE.value))
        if data.get("dca_state"):
            self.dca = DcaState.from_dict(data["dca_state"])
        if data.get("circuit_breaker"):
            self.circuit = PumpDumpCircuitBreaker.from_dict(data["circuit_breaker"])
        self.barrier_positions = {}
        for bp in data.get("barrier_positions") or []:
            pos = TripleBarrierPosition.from_dict(bp)
            self.barrier_positions[pos.level_id] = pos

    def persist_to_dict(self, data: dict[str, Any]) -> None:
        """Write executor state into bot dict for Redis persistence."""
        data["executor_state"] = self.state.value
        data["dca_state"] = self.dca.to_dict()
        data["circuit_breaker"] = self.circuit.to_dict()
        data["barrier_positions"] = [p.to_dict() for p in self.barrier_positions.values()]
        cfg = self._engine.config
        data["config"]["lower_price"] = cfg.lower_price
        data["config"]["upper_price"] = cfg.upper_price

    @classmethod
    def from_bot_data(cls, data: dict[str, Any]) -> GridExecutor:
        cfg = GridConfigModel.from_engine_dict(data.get("config", {}))
        ex = cls(cfg)
        ex.restore_from_dict(data)
        bot, _ = _restore_engine_from_data(data, ex._engine)
        ex._engine = bot
        return ex


def _restore_engine_from_data(data: dict[str, Any], bot: GridBotEngine) -> tuple[GridBotEngine, float]:
    bot.state.realized_pnl = data.get("realized_pnl", 0.0)
    bot.state.total_trades = data.get("total_trades", 0)
    bot.state.is_active = data.get("is_active", True)
    prev_price = data.get("summary", {}).get("last_price") or data.get("config", {}).get("entry_price", 0.0)
    bot.state.levels = []
    for l_data in data.get("levels", []):
        level = GridLevel(
            price=l_data["price"],
            side=l_data["side"],
            quantity=l_data["quantity"],
        )
        level.status = l_data.get("status", "pending")
        level.fill_price = l_data.get("fill_price")
        level.pnl = l_data.get("pnl", 0.0)
        if l_data.get("barrier_id"):
            level.barrier_id = l_data["barrier_id"]  # type: ignore[attr-defined]
        bot.state.levels.append(level)
    return bot, float(prev_price or 0.0)
