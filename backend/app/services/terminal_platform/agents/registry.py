"""Agent registry."""
from __future__ import annotations

from typing import Callable

from app.services.terminal_platform.agents.base import BaseAgent
from app.services.terminal_platform.agents.orchestrator import OrchestratorAgent
from app.services.terminal_platform.agents.schemas import AgentType
from app.services.terminal_platform.agents.specialists import (
    MacroAnalyst,
    MarketAnalyst,
    PortfolioStrategist,
    RiskOfficer,
    SectorAnalyst,
    TradeExecutor,
)
from app.services.terminal_platform.llm.base import LLMProvider
from app.services.terminal_platform.llm.factory import build_default_router
from app.services.terminal_platform.llm.router import LLMRouter

_AGENT_CLASSES: dict[AgentType, type[BaseAgent]] = {
    AgentType.MARKET_ANALYST: MarketAnalyst,
    AgentType.MACRO_ANALYST: MacroAnalyst,
    AgentType.SECTOR_ANALYST: SectorAnalyst,
    AgentType.PORTFOLIO_STRATEGIST: PortfolioStrategist,
    AgentType.RISK_OFFICER: RiskOfficer,
    AgentType.TRADE_EXECUTOR: TradeExecutor,
    AgentType.ORCHESTRATOR: OrchestratorAgent,
}


def list_agents() -> list[str]:
    return [a.value for a in AgentType]


def get_agent(
    agent_type: AgentType | str,
    llm: LLMRouter | LLMProvider | None = None,
) -> BaseAgent:
    if isinstance(agent_type, str):
        agent_type = AgentType(agent_type)
    cls = _AGENT_CLASSES.get(agent_type)
    if cls is None:
        raise KeyError(f"Unknown agent: {agent_type}")
    router = llm or build_default_router()
    return cls(router)


def agent_factory(agent_type: AgentType | str) -> Callable[[], BaseAgent]:
    def _factory() -> BaseAgent:
        return get_agent(agent_type)

    return _factory
