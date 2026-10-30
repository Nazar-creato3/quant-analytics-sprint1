"""
Risk Engine.
Computes position sizes, validates risk limits, generates stop/TP levels.
Uses % risk per trade methodology (Kelly fraction capped at configurable max).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.services.risk.portfolio_sizing import min_proposal_notional_usd, resolve_portfolio_size_usd

logger = get_logger(__name__)


@dataclass
class RiskParameters:
    """Per-trade risk parameters."""
    portfolio_size: float = field(default_factory=lambda: settings.DEFAULT_PORTFOLIO_SIZE)
    max_risk_pct: float = field(default_factory=lambda: settings.MAX_RISK_PER_TRADE_PCT)
    daily_max_loss_pct: float = field(default_factory=lambda: settings.DAILY_MAX_LOSS_PCT)
    max_exposure_pct: float = field(default_factory=lambda: settings.MAX_PORTFOLIO_EXPOSURE_PCT)
    max_drawdown_pct: float = field(default_factory=lambda: settings.MAX_DRAWDOWN_PCT)
    confidence_threshold: float = field(default_factory=lambda: settings.NO_TRADE_CONFIDENCE_THRESHOLD)
    # Never let one trade consume more than this share of total capital.
    max_position_pct: float = field(default_factory=lambda: settings.MAX_POSITION_PCT)
    # Optional absolute per-position notional cap in USD (0 = disabled).
    max_notional_per_position_usd: float = field(
        default_factory=lambda: settings.MAX_NOTIONAL_PER_POSITION_USD
    )

    def per_position_cap_usd(self) -> float:
        """Effective max USD for a single position (min of % cap and absolute cap)."""
        pct_cap = self.portfolio_size * self.max_position_pct / 100
        if self.max_notional_per_position_usd and self.max_notional_per_position_usd > 0:
            return min(pct_cap, self.max_notional_per_position_usd)
        return pct_cap


@dataclass
class TradeRiskResult:
    """Output of risk engine for a single trade idea."""
    ticker: str
    direction: str
    is_tradeable: bool
    reason: str

    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    invalidation_level: float = 0.0

    position_size_usd: float = 0.0
    position_size_shares: float = 0.0
    risk_amount_usd: float = 0.0
    risk_percent: float = 0.0

    expected_return_low_pct: float = 0.0
    expected_return_high_pct: float = 0.0
    expected_pnl_low: float = 0.0
    expected_pnl_high: float = 0.0

    risk_reward_ratio: float = 0.0


@dataclass
class PortfolioState:
    """Current portfolio exposure state — used for portfolio-level checks."""
    total_exposure_usd: float = 0.0
    daily_pnl_usd: float = 0.0
    current_drawdown_pct: float = 0.0
    open_positions: int = 0


class RiskEngine:
    """
    Risk-first position sizing and validation.

    Methodology:
    - Risk a fixed % of portfolio per trade.
    - Position size = Risk Amount / (Entry - Stop Loss)
    - Take Profit set at 2x risk by default (2:1 R:R minimum).
    - Return no-trade if any limit is breached.
    """

    def __init__(self, params: RiskParameters | None = None) -> None:
        self.params = params or RiskParameters()
        if self.params.portfolio_size <= 0:
            self.params.portfolio_size = resolve_portfolio_size_usd(self.params.portfolio_size)

    def compute(
        self,
        ticker: str,
        direction: str,              # "long" | "short"
        entry_price: float,
        confidence: float,
        atr: float,                  # ATR for dynamic stop placement
        portfolio_state: PortfolioState | None = None,
        custom_risk_pct: float | None = None,
        min_rr: float = 2.0,         # minimum risk:reward ratio
        confidence_threshold: float | None = None,
    ) -> TradeRiskResult:
        """
        Compute full risk parameters for a trade.

        Returns TradeRiskResult with is_tradeable=False if any limit is breached.
        """
        state = portfolio_state or PortfolioState()
        risk_pct = (
            min(float(custom_risk_pct), self.params.max_risk_pct)
            if custom_risk_pct is not None
            else self.params.max_risk_pct
        )
        threshold = (
            self.params.confidence_threshold
            if confidence_threshold is None
            else confidence_threshold
        )

        # ── Confidence gate ────────────────────────────────────────────────────
        if confidence < threshold:
            return TradeRiskResult(
                ticker=ticker, direction=direction, is_tradeable=False,
                reason=f"Confidence {confidence:.2%} below threshold {threshold:.2%}",
                entry_price=entry_price, risk_percent=risk_pct,
            )

        # ── Portfolio limits ───────────────────────────────────────────────────
        if state.daily_pnl_usd < -(self.params.portfolio_size * self.params.daily_max_loss_pct / 100):
            return TradeRiskResult(
                ticker=ticker, direction=direction, is_tradeable=False,
                reason=f"Daily loss limit reached: ${state.daily_pnl_usd:,.0f}",
                entry_price=entry_price, risk_percent=risk_pct,
            )

        if state.current_drawdown_pct > self.params.max_drawdown_pct:
            return TradeRiskResult(
                ticker=ticker, direction=direction, is_tradeable=False,
                reason=f"Drawdown limit reached: {state.current_drawdown_pct:.1f}%",
                entry_price=entry_price, risk_percent=risk_pct,
            )

        portfolio_usd = self.params.portfolio_size
        if portfolio_usd <= 0:
            portfolio_usd = resolve_portfolio_size_usd(portfolio_usd)
        exposure_pct = (state.total_exposure_usd / portfolio_usd) * 100 if portfolio_usd > 0 else 0.0
        if exposure_pct > self.params.max_exposure_pct:
            return TradeRiskResult(
                ticker=ticker, direction=direction, is_tradeable=False,
                reason=f"Max exposure reached: {exposure_pct:.1f}%",
                entry_price=entry_price, risk_percent=risk_pct,
            )

        # ── Stop loss placement (ATR-based) ────────────────────────────────────
        atr_multiplier = 2.0  # 2x ATR below entry for stop
        if direction == "long":
            stop_loss = entry_price - (atr * atr_multiplier)
            invalidation = stop_loss * 0.99  # slightly below stop
        elif direction == "short":
            stop_loss = entry_price + (atr * atr_multiplier)
            invalidation = stop_loss * 1.01
        else:
            return TradeRiskResult(
                ticker=ticker, direction=direction, is_tradeable=False,
                reason="Neutral direction — no trade",
                entry_price=entry_price, risk_percent=risk_pct,
            )

        if stop_loss <= 0:
            return TradeRiskResult(
                ticker=ticker, direction=direction, is_tradeable=False,
                reason="Invalid stop loss (≤ 0)",
                entry_price=entry_price, risk_percent=risk_pct,
            )

        risk_per_share = abs(entry_price - stop_loss)
        if risk_per_share < 0.001:
            return TradeRiskResult(
                ticker=ticker, direction=direction, is_tradeable=False,
                reason="Risk per share too small — ATR too low",
                entry_price=entry_price, risk_percent=risk_pct,
            )

        # ── Position sizing ────────────────────────────────────────────────────
        risk_amount = self.params.portfolio_size * (risk_pct / 100)
        position_shares = risk_amount / risk_per_share
        position_usd = position_shares * entry_price

        # Per-position cap: never risk the whole account on one idea. A tight
        # ATR stop would otherwise blow position size well past the portfolio.
        per_position_cap = self.params.per_position_cap_usd()

        # Remaining exposure budget also enforces the mandatory cash buffer.
        remaining_budget = (
            self.params.portfolio_size * self.params.max_exposure_pct / 100
            - state.total_exposure_usd
        )

        capped_usd = min(position_usd, per_position_cap, remaining_budget)
        min_ticket = min_proposal_notional_usd(self.params.portfolio_size)
        if capped_usd + 1e-6 < min_ticket:
            if remaining_budget + 1e-6 >= min_ticket and per_position_cap + 1e-6 >= min_ticket:
                capped_usd = min(min_ticket, per_position_cap, remaining_budget)
            else:
                return TradeRiskResult(
                    ticker=ticker, direction=direction, is_tradeable=False,
                    reason=(
                        f"Остаток бюджета ${remaining_budget:,.0f} меньше "
                        f"минимального слота ${min_ticket:,.0f} — не предлагать "
                        f"сделку на ${max(capped_usd, 0):,.0f}."
                    ),
                    entry_price=entry_price, risk_percent=risk_pct,
                )
        if capped_usd <= 0:
            return TradeRiskResult(
                ticker=ticker, direction=direction, is_tradeable=False,
                reason="Exposure budget exhausted — cash buffer protected",
                entry_price=entry_price, risk_percent=risk_pct,
            )
        if abs(capped_usd - position_usd) > 1e-6:
            position_usd = capped_usd
            position_shares = position_usd / entry_price
            risk_amount = position_shares * risk_per_share
            risk_pct = risk_amount / self.params.portfolio_size * 100

        # ── Take profit (min R:R enforced) ─────────────────────────────────────
        if direction == "long":
            take_profit = entry_price + (risk_per_share * min_rr)
            tp_return_pct = (take_profit - entry_price) / entry_price * 100
        else:
            take_profit = entry_price - (risk_per_share * min_rr)
            tp_return_pct = (entry_price - take_profit) / entry_price * 100

        # ── Expected return range (vol + horizon; overridden at maneuver assembly) ─
        conservative_return = tp_return_pct * 0.6
        optimistic_return = tp_return_pct * 1.2

        pnl_low = position_usd * (conservative_return / 100)
        pnl_high = position_usd * (optimistic_return / 100)

        rr = tp_return_pct / (risk_per_share / entry_price * 100) if risk_per_share > 0 else 0

        return TradeRiskResult(
            ticker=ticker,
            direction=direction,
            is_tradeable=True,
            reason="Risk checks passed",
            entry_price=entry_price,
            stop_loss=round(stop_loss, 4),
            take_profit=round(take_profit, 4),
            invalidation_level=round(invalidation, 4),
            position_size_usd=round(position_usd, 2),
            position_size_shares=round(position_shares, 4),
            risk_amount_usd=round(risk_amount, 2),
            risk_percent=risk_pct,
            expected_return_low_pct=round(conservative_return, 2),
            expected_return_high_pct=round(optimistic_return, 2),
            expected_pnl_low=round(pnl_low, 2),
            expected_pnl_high=round(pnl_high, 2),
            risk_reward_ratio=round(rr, 2),
        )

    def validate_portfolio(
        self,
        trades: list[TradeRiskResult],
        portfolio_size: float | None = None,
    ) -> tuple[list[TradeRiskResult], dict]:
        """
        Portfolio-level validation: total exposure, concentration checks.
        Returns filtered trades and a summary dict.
        """
        size = portfolio_size or self.params.portfolio_size
        total_exposure = sum(t.position_size_usd for t in trades if t.is_tradeable)
        max_exposure = size * self.params.max_exposure_pct / 100

        if total_exposure > max_exposure:
            # Scale all positions proportionally
            scale = max_exposure / total_exposure
            for trade in trades:
                if trade.is_tradeable:
                    trade.position_size_usd *= scale
                    trade.position_size_shares *= scale
                    trade.expected_pnl_low *= scale
                    trade.expected_pnl_high *= scale

        summary = {
            "total_exposure_usd": round(total_exposure, 2),
            "total_exposure_pct": round(total_exposure / size * 100, 2),
            "tradeable_count": sum(1 for t in trades if t.is_tradeable),
            "no_trade_count": sum(1 for t in trades if not t.is_tradeable),
        }
        return trades, summary


_risk_engine: RiskEngine | None = None


def get_risk_engine(params: RiskParameters | None = None) -> RiskEngine:
    global _risk_engine
    if _risk_engine is None:
        _risk_engine = RiskEngine(params)
    return _risk_engine
