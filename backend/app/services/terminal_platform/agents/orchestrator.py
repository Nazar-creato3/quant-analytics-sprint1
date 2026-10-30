"""OrchestratorAgent — ASKB-like query decomposition + multi-agent aggregation."""
from __future__ import annotations

import re
from typing import Any

from app.services.terminal_platform.agents.base import BaseAgent, parse_agent_answer
from app.services.terminal_platform.agents.context import AgentContext
from app.services.terminal_platform.agents.schemas import (
    AgentAnswer,
    AgentType,
    OrchestratorResult,
    OrchestratorSubResult,
)
from app.services.terminal_platform.agents.specialists import (
    MacroAnalyst,
    MarketAnalyst,
    PortfolioStrategist,
    RiskOfficer,
    SectorAnalyst,
    TradeExecutor,
)
from app.services.terminal_platform.llm.base import LLMConfig, LLMProvider
from app.services.terminal_platform.llm.router import LLMRouter
from app.services.terminal_platform.self_correcting.store import PredictionStore


_AGENT_KEYWORDS: list[tuple[AgentType, tuple[str, ...]]] = [
    (AgentType.MARKET_ANALYST, ("price", "ticker", "chart", "momentum", "volatility", "symbol", "quote")),
    (AgentType.MACRO_ANALYST, ("macro", "fed", "rate", "inflation", "cpi", "gdp", "risk-on", "risk-off")),
    (AgentType.SECTOR_ANALYST, ("sector", "industry", "peers", "rotation", "relative strength")),
    (AgentType.PORTFOLIO_STRATEGIST, ("portfolio", "allocation", "rebalance", "weight", "diversif")),
    (AgentType.RISK_OFFICER, ("risk", "var", "drawdown", "limit", "stress", "exposure")),
    (AgentType.TRADE_EXECUTOR, ("order", "execute", "buy", "sell", "entry", "size", "lot")),
]


class OrchestratorAgent(BaseAgent):
    """Decompose → route specialists → aggregate with confidence."""

    agent_type = AgentType.ORCHESTRATOR
    default_plan_steps = ["decompose", "dispatch", "aggregate"]

    def __init__(
        self,
        llm: LLMRouter | LLMProvider,
        *,
        prediction_store: PredictionStore | None = None,
        specialists: dict[AgentType, BaseAgent] | None = None,
    ) -> None:
        super().__init__(llm, prediction_store=prediction_store)
        if specialists is not None:
            self.specialists = specialists
        else:
            self.specialists = {
                AgentType.MARKET_ANALYST: MarketAnalyst(llm, prediction_store=self.prediction_store),
                AgentType.MACRO_ANALYST: MacroAnalyst(llm, prediction_store=self.prediction_store),
                AgentType.SECTOR_ANALYST: SectorAnalyst(llm, prediction_store=self.prediction_store),
                AgentType.PORTFOLIO_STRATEGIST: PortfolioStrategist(
                    llm, prediction_store=self.prediction_store
                ),
                AgentType.RISK_OFFICER: RiskOfficer(llm, prediction_store=self.prediction_store),
                AgentType.TRADE_EXECUTOR: TradeExecutor(llm, prediction_store=self.prediction_store),
            }

    def decompose(self, user_query: str) -> list[AgentType]:
        q = user_query.lower()
        selected: list[AgentType] = []
        for agent_type, kws in _AGENT_KEYWORDS:
            if any(k in q for k in kws):
                selected.append(agent_type)
        if not selected:
            # Broad default: market + risk
            selected = [AgentType.MARKET_ANALYST, AgentType.RISK_OFFICER]
        # Preserve order, unique
        seen: set[AgentType] = set()
        out: list[AgentType] = []
        for a in selected:
            if a not in seen:
                seen.add(a)
                out.append(a)
        return out

    def _aggregate(self, query: str, sub: list[OrchestratorSubResult]) -> AgentAnswer:
        if not sub:
            return AgentAnswer(
                answer="No specialist results",
                confidence=0.0,
                confidence_reason="Empty orchestration",
                data_sources=[],
                assumptions=[],
                risks=["No agents ran"],
                agent_type=AgentType.ORCHESTRATOR,
            )

        # Confidence-weighted blend
        weights = [max(0.05, s.answer.confidence) for s in sub]
        wsum = sum(weights) or 1.0
        blended = sum(s.answer.confidence * w for s, w in zip(sub, weights)) / wsum
        # Penalize disagreement (spread of confidences)
        mean_c = sum(s.answer.confidence for s in sub) / len(sub)
        spread = sum(abs(s.answer.confidence - mean_c) for s in sub) / len(sub)
        final_conf = max(0.0, min(1.0, blended * (1.0 - 0.5 * spread)))

        parts = [f"[{s.agent_type}] {s.answer.answer}" for s in sub]
        sources: list[str] = []
        assumptions: list[str] = []
        risks: list[str] = []
        for s in sub:
            sources.extend(s.answer.data_sources)
            assumptions.extend(s.answer.assumptions)
            risks.extend(s.answer.risks)

        return AgentAnswer(
            answer="\n\n".join(parts),
            confidence=round(final_conf, 4),
            confidence_reason=(
                f"Weighted mean of {len(sub)} specialists "
                f"(spread={spread:.2f}); query={query[:80]!r}"
            ),
            data_sources=list(dict.fromkeys(sources)),
            assumptions=list(dict.fromkeys(assumptions)),
            risks=list(dict.fromkeys(risks)),
            agent_type=AgentType.ORCHESTRATOR,
            metadata={"n_agents": len(sub)},
        )

    async def run(
        self,
        user_query: str,
        context: AgentContext | None = None,
        *,
        agent_types: list[AgentType | str] | None = None,
    ) -> OrchestratorResult:
        if agent_types:
            decomposition: list[AgentType] = []
            for a in agent_types:
                decomposition.append(AgentType(a) if isinstance(a, str) else a)
        else:
            decomposition = self.decompose(user_query)

        sub_results: list[OrchestratorSubResult] = []
        for agent_type in decomposition:
            agent = self.specialists.get(agent_type)
            if agent is None:
                continue
            # Narrow prompt for the specialist
            result = await agent.execute(user_query, context)
            sub_results.append(
                OrchestratorSubResult(agent_type=agent_type, answer=result.answer)
            )

        aggregated = self._aggregate(user_query, sub_results)

        # Optional LLM polish of the aggregate (best-effort; keep heuristic if fails)
        try:
            cfg = LLMConfig(temperature=0.2, max_tokens=1200, response_format="json_object")
            system = (
                "You synthesize specialist financial agent outputs into one JSON answer "
                "with keys answer, confidence, confidence_reason, data_sources, "
                "assumptions, risks. Preserve key risks; calibrate confidence."
            )
            synthesis_ctx: dict[str, Any] = {
                "query": user_query,
                "specialists": [s.model_dump(mode="json") for s in sub_results],
                "heuristic_aggregate": aggregated.model_dump(mode="json"),
            }
            if isinstance(self.llm, LLMRouter):
                resp = await self.llm.generate_with_fallback(
                    "Synthesize the final answer JSON.",
                    context=synthesis_ctx,
                    config=cfg,
                    system=system,
                )
            else:
                resp = await self.llm.generate(
                    "Synthesize the final answer JSON.",
                    context=synthesis_ctx,
                    config=cfg,
                    system=system,
                )
            polished = parse_agent_answer(resp.content, agent_type=AgentType.ORCHESTRATOR)
            # Blend heuristic confidence with LLM confidence (conservative min)
            polished.confidence = min(polished.confidence, aggregated.confidence)
            polished.provider = resp.provider
            polished.model = resp.model
            polished.data_sources = list(
                dict.fromkeys([*aggregated.data_sources, *polished.data_sources])
            )
            polished.risks = list(dict.fromkeys([*aggregated.risks, *polished.risks]))
            aggregated = polished
        except Exception:  # noqa: BLE001 — keep heuristic aggregate
            pass

        pred_id = self.prediction_store.log_prediction(
            agent_type=AgentType.ORCHESTRATOR.value,
            query=user_query,
            answer=aggregated,
        )
        aggregated.metadata["prediction_id"] = pred_id

        return OrchestratorResult(
            query=user_query,
            decomposition=[a.value for a in decomposition],
            sub_results=sub_results,
            aggregated=aggregated,
        )


def extract_symbols(query: str) -> list[str]:
    """Best-effort ticker extraction (uppercase tokens 1–5 chars)."""
    return re.findall(r"\b[A-Z]{1,5}\b", query)
