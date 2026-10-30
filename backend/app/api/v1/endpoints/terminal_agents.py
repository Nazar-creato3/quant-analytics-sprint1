"""Terminal AI agents API — /api/v1/terminal/agents/."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.deps import get_current_user_email

from app.services.terminal_platform.agents.context import (
    AgentContext,
    MacroContext,
    MarketContext,
    PortfolioContext,
    RiskContext,
    SectorContext,
)
from app.services.terminal_platform.agents.orchestrator import OrchestratorAgent
from app.services.terminal_platform.agents.registry import get_agent, list_agents
from app.services.terminal_platform.agents.schemas import AgentType
from app.services.terminal_platform.llm.base import LLMProviderError
from app.services.terminal_platform.llm.factory import build_default_router
from app.services.terminal_platform.self_correcting.store import (
    PredictionStore,
    self_review,
)

router = APIRouter(
    prefix="/terminal/agents",
    tags=["terminal-agents"],
    dependencies=[Depends(get_current_user_email)],
)

_GENERIC = "сейчас не получилось"


class AgentAskRequest(BaseModel):
    query: str = Field(..., min_length=1)
    agent_type: AgentType = AgentType.MARKET_ANALYST
    context: dict[str, Any] | None = None
    symbol: str | None = None


class OrchestrateRequest(BaseModel):
    query: str = Field(..., min_length=1)
    agent_types: list[AgentType] | None = None
    context: dict[str, Any] | None = None
    symbol: str | None = None


class OutcomeRequest(BaseModel):
    prediction_id: str
    outcome: str
    correct: bool | None = None
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    review_notes: str | None = None
    expected_keywords: list[str] | None = None
    auto_review: bool = False


def _build_context(
    raw: dict[str, Any] | None,
    *,
    symbol: str | None = None,
) -> AgentContext:
    raw = raw or {}
    market = raw.get("market")
    if symbol and not market:
        market = {"symbol": symbol}
    elif symbol and isinstance(market, dict) and not market.get("symbol"):
        market = {**market, "symbol": symbol}

    def _maybe(model_cls, key: str):
        val = raw.get(key)
        if val is None:
            return None
        if isinstance(val, dict):
            return model_cls.model_validate(val)
        return None

    return AgentContext(
        market=MarketContext.model_validate(market) if isinstance(market, dict) else None,
        macro=_maybe(MacroContext, "macro"),
        sector=_maybe(SectorContext, "sector"),
        risk=_maybe(RiskContext, "risk"),
        portfolio=_maybe(PortfolioContext, "portfolio"),
        extra={k: v for k, v in raw.items() if k not in {"market", "macro", "sector", "risk", "portfolio"}},
    )


@router.get("")
async def agents_index():
    return {
        "agents": list_agents(),
        "endpoints": {
            "ask": "POST /terminal/agents/ask",
            "orchestrate": "POST /terminal/agents/orchestrate",
            "metrics": "GET /terminal/agents/metrics",
            "predictions": "GET /terminal/agents/predictions",
            "outcome": "POST /terminal/agents/predictions/outcome",
        },
    }


@router.get("/list")
async def agents_list():
    return {"items": list_agents()}


@router.post("/ask")
async def ask_agent(
    body: AgentAskRequest,
    email: str = Depends(get_current_user_email),
):
    router_llm = build_default_router()
    ctx = _build_context(body.context, symbol=body.symbol)
    token = PredictionStore.bind_owner(email)
    try:
        if body.agent_type == AgentType.ORCHESTRATOR:
            orch = OrchestratorAgent(router_llm)
            result = await orch.run(body.query, ctx)
            return result.model_dump(mode="json")
        agent = get_agent(body.agent_type, llm=router_llm)
        result = await agent.execute(body.query, ctx)
        return result.model_dump(mode="json")
    except LLMProviderError as exc:
        raise HTTPException(status_code=503, detail=_GENERIC) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_GENERIC) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=_GENERIC) from exc
    finally:
        PredictionStore.reset_owner(token)


@router.post("/orchestrate")
async def orchestrate(
    body: OrchestrateRequest,
    email: str = Depends(get_current_user_email),
):
    router_llm = build_default_router()
    ctx = _build_context(body.context, symbol=body.symbol)
    orch = OrchestratorAgent(router_llm)
    token = PredictionStore.bind_owner(email)
    try:
        result = await orch.run(body.query, ctx, agent_types=body.agent_types)
        return result.model_dump(mode="json")
    except LLMProviderError as exc:
        raise HTTPException(status_code=503, detail=_GENERIC) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=_GENERIC) from exc
    finally:
        PredictionStore.reset_owner(token)


@router.get("/metrics")
async def agent_metrics(email: str = Depends(get_current_user_email)):
    store = PredictionStore.instance()
    return store.metrics(owner_id=email).model_dump(mode="json")


@router.get("/predictions")
async def list_predictions(limit: int = 50, email: str = Depends(get_current_user_email)):
    store = PredictionStore.instance()
    return {
        "items": [
            r.model_dump(mode="json", exclude={"owner_id"})
            for r in store.list_records(limit=limit, owner_id=email)
        ]
    }


@router.post("/predictions/outcome")
async def record_prediction_outcome(
    body: OutcomeRequest,
    email: str = Depends(get_current_user_email),
):
    store = PredictionStore.instance()
    token = PredictionStore.bind_owner(email)
    try:
        rec = store.get(body.prediction_id, owner_id=email)
        if rec is None:
            raise HTTPException(404, _GENERIC)

        correct = body.correct
        score = body.score
        notes = body.review_notes
        outcome = body.outcome

        if body.auto_review:
            review = self_review(
                rec, outcome=outcome, expected_keywords=body.expected_keywords
            )
            correct = review["correct"] if correct is None else correct
            score = review["score"] if score is None else score
            notes = notes or review["review_notes"]

        updated = store.record_outcome(
            body.prediction_id,
            outcome=outcome,
            correct=correct,
            score=score,
            review_notes=notes,
        )
        return updated.model_dump(mode="json")
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(404, _GENERIC) from exc
    finally:
        PredictionStore.reset_owner(token)
