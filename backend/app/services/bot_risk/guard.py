"""
Unified bot risk guard — shared across Grid, DCA, Momentum, and future bots.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.services.bot_risk.instruments import instruments_correlated, normalize_instrument_key
from app.services.bot_risk.portfolio import (
    build_portfolio_snapshot,
    list_exposed_instruments,
)
from app.services.bot_risk.position_sizing import (
    compute_risk_based_size,
    default_stop_loss_price,
)
from app.services.bot_risk.types import (
    BotRef,
    CircuitBreakerResult,
    CorrelationCheckResult,
    CorrelationMode,
    NewPositionGateResult,
    PortfolioSnapshot,
    PositionSizeResult,
)
from app.services.bots.common import append_event

logger = get_logger(__name__)


@dataclass
class BotRiskConfig:
    risk_per_trade_pct: float
    circuit_breaker_drawdown_pct: float
    correlation_mode: CorrelationMode
    default_stop_loss_pct: float
    max_position_pct: float

    @classmethod
    def from_settings(cls) -> BotRiskConfig:
        mode_raw = (settings.BOT_CORRELATION_MODE or "block").strip().lower()
        try:
            mode = CorrelationMode(mode_raw)
        except ValueError:
            mode = CorrelationMode.BLOCK
        return cls(
            risk_per_trade_pct=float(settings.BOT_RISK_PER_TRADE_PCT),
            circuit_breaker_drawdown_pct=float(settings.BOT_CIRCUIT_BREAKER_DRAWDOWN_PCT),
            correlation_mode=mode,
            default_stop_loss_pct=float(settings.BOT_DEFAULT_STOP_LOSS_PCT),
            max_position_pct=float(settings.MAX_POSITION_PCT),
        )


class BotRiskGuard:
    def __init__(self, config: BotRiskConfig | None = None) -> None:
        self.config = config or BotRiskConfig.from_settings()

    def default_grid_stop_loss(self, lower_bound: float) -> float:
        return default_stop_loss_price(
            entry_price=lower_bound,
            stop_loss_pct=self.config.default_stop_loss_pct,
            direction="long",
            anchor_price=lower_bound,
        )

    def compute_position_size(
        self,
        *,
        portfolio_usd: float,
        entry_price: float,
        stop_loss_price: float,
        direction: str = "long",
        risk_pct: float | None = None,
    ) -> PositionSizeResult:
        return compute_risk_based_size(
            portfolio_usd=portfolio_usd,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            risk_pct=risk_pct if risk_pct is not None else self.config.risk_per_trade_pct,
            max_position_pct=self.config.max_position_pct,
            direction=direction,
        )

    def check_correlation(
        self,
        *,
        ticker: str,
        snapshot: PortfolioSnapshot,
        exclude_bot_id: str | None = None,
    ) -> CorrelationCheckResult:
        target_key = normalize_instrument_key(ticker)
        if not target_key:
            return CorrelationCheckResult(
                allowed=True,
                mode=self.config.correlation_mode,
                reason="No ticker to correlate",
            )

        conflicts: list[str] = []
        for bot_id, bot_type, key in list_exposed_instruments(
            snapshot.bots, exclude_bot_id=exclude_bot_id
        ):
            if instruments_correlated(ticker, key) or key == target_key:
                conflicts.append(f"{bot_type}:{bot_id}")

        if not conflicts:
            return CorrelationCheckResult(
                allowed=True,
                mode=self.config.correlation_mode,
                reason="No correlated exposure",
            )

        reason = (
            f"Correlated exposure on {target_key}: "
            + ", ".join(conflicts[:5])
        )
        if self.config.correlation_mode == CorrelationMode.WARN:
            return CorrelationCheckResult(
                allowed=True,
                mode=self.config.correlation_mode,
                reason=f"WARN — {reason}",
                conflicting_bots=conflicts,
            )
        return CorrelationCheckResult(
            allowed=False,
            mode=self.config.correlation_mode,
            reason=reason,
            conflicting_bots=conflicts,
        )

    def evaluate_circuit_breaker(self, snapshot: PortfolioSnapshot) -> CircuitBreakerResult:
        threshold = self.config.circuit_breaker_drawdown_pct
        dd = snapshot.drawdown_pct
        tripped = dd >= threshold and snapshot.allocated_usd > 0
        reason = ""
        if tripped:
            reason = (
                f"Portfolio drawdown {dd:.2f}% >= limit {threshold:.2f}% "
                f"(PnL ${snapshot.total_pnl:,.2f} on ${snapshot.allocated_usd:,.0f} allocated)"
            )
        return CircuitBreakerResult(
            tripped=tripped,
            drawdown_pct=round(dd, 4),
            threshold_pct=threshold,
            total_pnl=round(snapshot.total_pnl, 4),
            allocated_usd=round(snapshot.allocated_usd, 2),
            reason=reason,
        )

    def gate_new_position(
        self,
        *,
        ticker: str,
        portfolio_usd: float,
        entry_price: float,
        stop_loss_price: float,
        snapshot: PortfolioSnapshot,
        bot_id: str,
        direction: str = "long",
    ) -> NewPositionGateResult:
        corr = self.check_correlation(
            ticker=ticker,
            snapshot=snapshot,
            exclude_bot_id=bot_id,
        )
        if not corr.allowed:
            return NewPositionGateResult(
                allowed=False,
                reason=corr.reason,
                correlation=corr,
            )

        sizing = self.compute_position_size(
            portfolio_usd=portfolio_usd,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            direction=direction,
        )
        if not sizing.allowed:
            return NewPositionGateResult(
                allowed=False,
                reason=sizing.reason,
                correlation=corr,
                sizing=sizing,
            )

        msg = corr.reason if corr.conflicting_bots else "Risk gate passed"
        return NewPositionGateResult(
            allowed=True,
            reason=msg,
            correlation=corr,
            sizing=sizing,
        )

    def apply_portfolio_halt(
        self,
        refs: list[BotRef],
        *,
        reason: str,
    ) -> int:
        """Pause all active bots and mark risk halt. Returns count halted."""
        count = 0
        for ref in refs:
            data = ref.data
            if not data.get("is_active", True):
                continue
            if data.get("risk_halt") and data.get("is_paused"):
                continue
            data["is_paused"] = True
            data["risk_halt"] = True
            append_event(
                data,
                "risk_circuit_breaker",
                reason,
            )
            count += 1
        return count


_guard: BotRiskGuard | None = None


def get_bot_risk_guard() -> BotRiskGuard:
    global _guard
    if _guard is None:
        _guard = BotRiskGuard()
    return _guard


def build_snapshot_from_stores(
    *,
    grid: dict[str, dict[str, Any]] | None = None,
    dca: dict[str, dict[str, Any]] | None = None,
    momentum: dict[str, dict[str, Any]] | None = None,
    peak_pnl: float = 0.0,
) -> PortfolioSnapshot:
    from app.services.bot_risk.portfolio import build_bot_refs

    refs = build_bot_refs(grid=grid, dca=dca, momentum=momentum)
    return build_portfolio_snapshot(refs, peak_pnl=peak_pnl)


async def load_peak_pnl() -> float:
    try:
        from app.utils.cache import cache_get

        raw = await cache_get("bot_risk:peak_pnl")
        return float(raw) if raw is not None else 0.0
    except Exception:
        return 0.0


async def save_peak_pnl(peak: float) -> None:
    try:
        from app.utils.cache import cache_set

        await cache_set("bot_risk:peak_pnl", round(peak, 4), ttl=86400 * 30)
    except Exception as exc:
        logger.debug("Could not persist bot risk peak", error=str(exc))


async def run_portfolio_circuit_breaker(
    *,
    grid: dict[str, dict[str, Any]] | None = None,
    dca: dict[str, dict[str, Any]] | None = None,
    momentum: dict[str, dict[str, Any]] | None = None,
) -> CircuitBreakerResult | None:
    """
    Evaluate portfolio drawdown and halt all bots if threshold exceeded.
    Persists peak PnL in Redis for cross-tick drawdown tracking.
    """
    guard = get_bot_risk_guard()
    peak = await load_peak_pnl()
    snapshot = build_snapshot_from_stores(
        grid=grid, dca=dca, momentum=momentum, peak_pnl=peak
    )
    result = guard.evaluate_circuit_breaker(snapshot)
    new_peak = max(peak, snapshot.total_pnl)
    await save_peak_pnl(new_peak)

    if not result.tripped:
        return result

    refs = snapshot.bots
    halted = guard.apply_portfolio_halt(refs, reason=result.reason)
    logger.warning(
        "Bot portfolio circuit breaker tripped",
        drawdown_pct=result.drawdown_pct,
        halted=halted,
        reason=result.reason,
    )
    await _notify_circuit_breaker(result, halted)
    return result


async def _notify_circuit_breaker(result: CircuitBreakerResult, halted: int) -> None:
    message = (
        f"Bot circuit breaker: {result.reason}. "
        f"Paused {halted} bot(s)."
    )
    try:
        from app.services.event_bus.bus import publish_event

        publish_event(
            "bot.circuit_breaker",
            {
                "reason": result.reason,
                "drawdown_pct": result.drawdown_pct,
                "halted_bots": halted,
                "user_id": "system",
            },
        )
    except Exception:
        logger.debug("event_bus circuit breaker skip")
    try:
        from app.utils.ws_notify import notify_cockpit_sync

        notify_cockpit_sync(
            "BOT_RISK",
            {
                "event": "circuit_breaker",
                "drawdown_pct": result.drawdown_pct,
                "threshold_pct": result.threshold_pct,
                "halted_bots": halted,
                "reason": result.reason,
            },
        )
    except Exception as exc:
        logger.debug("WS circuit breaker notify failed", error=str(exc))

    if settings.telegram_configured:
        try:
            from app.services.alerts.telegram import send_telegram_message

            await send_telegram_message(message)
        except Exception as exc:
            logger.debug("Telegram circuit breaker notify failed", error=str(exc))
