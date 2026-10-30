"""Concrete terminal agents."""
from __future__ import annotations

from app.services.terminal_platform.agents.base import BaseAgent
from app.services.terminal_platform.agents.schemas import AgentType


class MarketAnalyst(BaseAgent):
    agent_type = AgentType.MARKET_ANALYST
    default_plan_steps = [
        "load_recent_bars",
        "compute_momentum_volatility",
        "detect_regime",
        "synthesize_view",
    ]


class MacroAnalyst(BaseAgent):
    agent_type = AgentType.MACRO_ANALYST
    default_plan_steps = [
        "load_macro_snapshot",
        "assess_policy_path",
        "risk_on_off_score",
        "synthesize_view",
    ]


class SectorAnalyst(BaseAgent):
    agent_type = AgentType.SECTOR_ANALYST
    default_plan_steps = [
        "identify_sector",
        "relative_strength_vs_benchmark",
        "peer_dispersion",
        "synthesize_view",
    ]


class PortfolioStrategist(BaseAgent):
    agent_type = AgentType.PORTFOLIO_STRATEGIST
    default_plan_steps = [
        "load_positions",
        "measure_concentration",
        "propose_rebalance",
        "synthesize_view",
    ]


class RiskOfficer(BaseAgent):
    agent_type = AgentType.RISK_OFFICER
    default_plan_steps = [
        "load_limits",
        "compute_var_drawdown",
        "run_stress_checks",
        "flag_breaches",
    ]


class TradeExecutor(BaseAgent):
    agent_type = AgentType.TRADE_EXECUTOR
    default_plan_steps = [
        "parse_trade_intent",
        "size_orders",
        "apply_constraints",
        "emit_order_intents",
    ]
