"""Base Agent — plan / execute / format with structured LLM output."""
from __future__ import annotations

import json
import re
from typing import Any

from app.services.terminal_platform.agents.context import AgentContext
from app.services.terminal_platform.agents.prompts import system_prompt_for
from app.services.terminal_platform.agents.schemas import (
    AgentAnswer,
    AgentPlan,
    AgentResult,
    AgentType,
)
from app.services.terminal_platform.llm.base import LLMConfig, LLMProvider
from app.services.terminal_platform.llm.router import LLMRouter
from app.services.terminal_platform.self_correcting.store import PredictionStore


_JSON_RE = re.compile(r"\{[\s\S]*\}")


def parse_agent_answer(raw: str, *, agent_type: AgentType | str | None = None) -> AgentAnswer:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data: dict[str, Any] | None = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_RE.search(text)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                data = None
    if not isinstance(data, dict):
        return AgentAnswer(
            answer=text or "No response",
            confidence=0.35,
            confidence_reason="LLM returned non-JSON; confidence lowered",
            data_sources=[],
            assumptions=["Response was free-form text"],
            risks=["Structured fields missing"],
            agent_type=agent_type,
        )

    conf = data.get("confidence", 0.5)
    try:
        conf_f = float(conf)
    except (TypeError, ValueError):
        conf_f = 0.5
    conf_f = max(0.0, min(1.0, conf_f))

    def _list(key: str) -> list[str]:
        val = data.get(key) or []
        if isinstance(val, str):
            return [val]
        if isinstance(val, list):
            return [str(x) for x in val]
        return []

    return AgentAnswer(
        answer=str(data.get("answer") or text),
        confidence=conf_f,
        confidence_reason=str(data.get("confidence_reason") or "Not provided"),
        data_sources=_list("data_sources"),
        assumptions=_list("assumptions"),
        risks=_list("risks"),
        agent_type=agent_type,
    )


class BaseAgent:
    """Role-based agent with structured output contract."""

    agent_type: AgentType = AgentType.MARKET_ANALYST
    default_plan_steps: list[str] = ["gather_context", "analyze", "respond"]

    def __init__(
        self,
        llm: LLMRouter | LLMProvider,
        *,
        prediction_store: PredictionStore | None = None,
    ) -> None:
        self.llm = llm
        self.prediction_store = prediction_store or PredictionStore.instance()

    def plan(self, user_query: str, context: AgentContext | None = None) -> AgentPlan:
        symbols: list[str] = []
        if context and context.market and context.market.symbol:
            symbols.append(context.market.symbol)
        return AgentPlan(
            steps=list(self.default_plan_steps),
            tools_needed=[],
            focus_symbols=symbols,
        )

    async def execute(
        self,
        user_query: str,
        context: AgentContext | None = None,
        *,
        plan: AgentPlan | None = None,
    ) -> AgentResult:
        plan = plan or self.plan(user_query, context)
        ctx_payload = context.to_llm_dict() if context else {}
        cfg = LLMConfig(temperature=0.3, max_tokens=2048, response_format="json_object")
        system = system_prompt_for(self.agent_type)
        prompt = (
            f"User query:\n{user_query}\n\n"
            f"Plan steps: {plan.steps}\n"
            "Produce the JSON response now."
        )

        if isinstance(self.llm, LLMRouter):
            resp = await self.llm.generate_with_fallback(
                prompt, context=ctx_payload, config=cfg, system=system
            )
        else:
            resp = await self.llm.generate(
                prompt, context=ctx_payload, config=cfg, system=system
            )

        answer = parse_agent_answer(resp.content, agent_type=self.agent_type)
        answer.provider = resp.provider
        answer.model = resp.model
        answer.metadata = {"plan_steps": plan.steps}

        pred_id = self.prediction_store.log_prediction(
            agent_type=str(self.agent_type.value if isinstance(self.agent_type, AgentType) else self.agent_type),
            query=user_query,
            answer=answer,
        )
        answer.metadata["prediction_id"] = pred_id

        return AgentResult(plan=plan, answer=answer, raw_llm=resp.content)

    def format_result(self, result: AgentResult) -> str:
        a = result.answer
        return (
            f"{a.answer}\n\n"
            f"Confidence: {a.confidence:.0%} — {a.confidence_reason}\n"
            f"Risks: {', '.join(a.risks) or 'n/a'}"
        )
