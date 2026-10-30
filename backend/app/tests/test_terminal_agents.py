"""Tests for terminal platform LLM providers, agents, orchestrator (mocked LLM)."""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.services.terminal_platform.agents.base import parse_agent_answer
from app.services.terminal_platform.agents.context import AgentContext, MarketContext
from app.services.terminal_platform.agents.orchestrator import OrchestratorAgent
from app.services.terminal_platform.agents.registry import get_agent, list_agents
from app.services.terminal_platform.agents.schemas import AgentAnswer, AgentType
from app.services.terminal_platform.agents.specialists import MarketAnalyst, RiskOfficer
from app.services.terminal_platform.llm.base import (
    LLMConfig,
    LLMProvider,
    LLMProviderError,
    LLMResponse,
)
from app.services.terminal_platform.llm.factory import create_provider
from app.services.terminal_platform.llm.providers import (
    AnthropicProvider,
    GeminiProvider,
    OpenAIProvider,
)
from app.services.terminal_platform.llm.router import LLMRouter
from app.services.terminal_platform.self_correcting.store import (
    PredictionStore,
    self_review,
)


class MockLLM(LLMProvider):
    name = "mock"
    model = "mock-1"
    supports_tools = False

    def __init__(self, content: str | None = None, *, fail: bool = False) -> None:
        self._content = content
        self.fail = fail
        self.calls = 0

    def is_available(self) -> bool:
        return not self.fail or True  # available even if generate fails

    async def generate(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | str | None = None,
        tools=None,
        config: LLMConfig | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        self.calls += 1
        if self.fail:
            raise LLMProviderError(self.name, "mock failure", retryable=True)
        payload = self._content or json.dumps(
            {
                "answer": "Bullish short-term",
                "confidence": 0.72,
                "confidence_reason": "Momentum positive",
                "data_sources": ["mock_ohlcv"],
                "assumptions": ["No regime change"],
                "risks": ["Gap risk"],
            }
        )
        return LLMResponse(content=payload, provider=self.name, model=self.model)


def _json_answer(**overrides: Any) -> str:
    base = {
        "answer": "ok",
        "confidence": 0.6,
        "confidence_reason": "test",
        "data_sources": ["x"],
        "assumptions": ["a"],
        "risks": ["r"],
    }
    base.update(overrides)
    return json.dumps(base)


@pytest.fixture(autouse=True)
def _reset_store():
    PredictionStore.reset_instance()
    yield
    PredictionStore.reset_instance()


def test_list_agents_includes_specialists():
    names = list_agents()
    assert "market_analyst" in names
    assert "trade_executor" in names
    assert "orchestrator" in names


def test_parse_agent_answer_json_and_fallback():
    ans = parse_agent_answer(_json_answer(confidence=0.9), agent_type=AgentType.MARKET_ANALYST)
    assert ans.confidence == 0.9
    assert ans.data_sources == ["x"]
    free = parse_agent_answer("just text", agent_type="market_analyst")
    assert free.confidence <= 0.4
    assert "non-JSON" in free.confidence_reason or free.answer == "just text"


def test_create_provider_names():
    for name in (
        "openai",
        "anthropic",
        "gemini",
        "groq",
        "deepseek",
        "ollama",
        "openrouter",
        "aitunnel",
    ):
        p = create_provider(name)
        assert p.name == name


def test_openai_provider_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    p = OpenAIProvider(api_key="")
    assert p.is_available() is False


@pytest.mark.asyncio
async def test_openai_provider_calls_api_when_keyed(monkeypatch):
    p = OpenAIProvider(api_key="sk-test", model="gpt-4.1", base_url="https://api.openai.com/v1")
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = lambda: None
    mock_resp.json = lambda: {
        "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.terminal_platform.llm.openai_compat.httpx.AsyncClient", return_value=mock_client):
        out = await p.generate("ping", system="sys")
    assert out.content == "hi"
    assert out.provider == "openai"
    assert mock_client.post.called


@pytest.mark.asyncio
async def test_anthropic_provider_calls_messages_api():
    p = AnthropicProvider(api_key="sk-ant", model="claude-test")
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = lambda: None
    mock_resp.json = lambda: {
        "content": [{"type": "text", "text": "anthropic-ok"}],
        "usage": {"input_tokens": 2, "output_tokens": 3},
        "stop_reason": "end_turn",
    }
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.terminal_platform.llm.providers.httpx.AsyncClient", return_value=mock_client):
        out = await p.generate("q", system="s")
    assert out.content == "anthropic-ok"
    body = mock_client.post.call_args[1]["json"]
    assert body["model"] == "claude-test"
    assert "system" in body


@pytest.mark.asyncio
async def test_gemini_provider_calls_generate_content():
    p = GeminiProvider(api_key="gem-key", model="gemini-2.5-pro")
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = lambda: None
    mock_resp.json = lambda: {
        "candidates": [{"content": {"parts": [{"text": "gemini-ok"}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
    }
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.terminal_platform.llm.providers.httpx.AsyncClient", return_value=mock_client):
        out = await p.generate("q")
    assert out.content == "gemini-ok"
    assert "generateContent" in mock_client.post.call_args[0][0]


@pytest.mark.asyncio
async def test_llm_router_fallback():
    bad = MockLLM(fail=True)
    bad.name = "bad"
    good = MockLLM(_json_answer(answer="fallback-ok", confidence=0.55))
    good.name = "good"
    router = LLMRouter([bad, good])
    resp = await router.generate_with_fallback("hi")
    assert resp.provider == "good"
    assert router.last_provider == "good"
    assert bad.calls == 1
    assert good.calls == 1


@pytest.mark.asyncio
async def test_market_analyst_structured_output():
    llm = MockLLM()
    agent = MarketAnalyst(llm)
    ctx = AgentContext(market=MarketContext(symbol="SBER", regime="trend"))
    result = await agent.execute("Analyze SBER momentum", ctx)
    assert result.answer.confidence == 0.72
    assert result.answer.data_sources == ["mock_ohlcv"]
    assert result.answer.agent_type == AgentType.MARKET_ANALYST
    assert result.answer.metadata.get("prediction_id")


@pytest.mark.asyncio
async def test_orchestrator_decomposition_and_aggregation():
    llm = MockLLM(
        _json_answer(
            answer="synth",
            confidence=0.8,
            confidence_reason="blend",
            risks=["vol"],
        )
    )
    orch = OrchestratorAgent(llm)
    # Force only market + risk via keywords
    out = await orch.run("What is the price risk and drawdown for the portfolio?")
    assert AgentType.RISK_OFFICER.value in out.decomposition or "risk_officer" in out.decomposition
    assert out.aggregated.answer
    assert 0.0 <= out.aggregated.confidence <= 1.0
    assert out.sub_results


@pytest.mark.asyncio
async def test_orchestrator_explicit_agent_types():
    llm = MockLLM()
    orch = OrchestratorAgent(llm)
    out = await orch.run(
        "hello",
        agent_types=[AgentType.MACRO_ANALYST],
    )
    assert out.decomposition == ["macro_analyst"]
    assert len(out.sub_results) == 1


def test_prediction_store_metrics_and_self_review():
    store = PredictionStore.instance()
    ans = AgentAnswer(
        answer="Rates will stay high",
        confidence=0.7,
        confidence_reason="sticky inflation",
        data_sources=["cpi"],
        assumptions=[],
        risks=[],
        agent_type=AgentType.MACRO_ANALYST,
    )
    pid = store.log_prediction(agent_type="macro_analyst", query="rates?", answer=ans)
    review = self_review(store.get(pid), outcome="inflation sticky high rates", expected_keywords=["rates", "high"])
    store.record_outcome(pid, outcome=review["outcome"], correct=review["correct"], score=review["score"], review_notes=review["review_notes"])
    m = store.metrics()
    assert m.total_predictions == 1
    assert m.scored == 1
    assert m.accuracy == 1.0
    assert "macro_analyst" in m.by_agent


def test_prediction_store_hides_foreign_owner():
    PredictionStore.reset_instance()
    store = PredictionStore.instance()
    ans = AgentAnswer(
        answer="Rates will stay high",
        confidence=0.7,
        confidence_reason="sticky inflation",
        data_sources=["cpi"],
        assumptions=[],
        risks=[],
        agent_type=AgentType.MACRO_ANALYST,
    )
    alice = store.log_prediction(agent_type="macro_analyst", query="a?", answer=ans, owner_id="alice@x")
    store.log_prediction(agent_type="macro_analyst", query="b?", answer=ans, owner_id="bob@x")
    assert [r.id for r in store.list_records(owner_id="alice@x")] == [alice]
    assert store.get(alice, owner_id="bob@x") is None
    assert store.metrics(owner_id="bob@x").total_predictions == 1


@pytest.mark.asyncio
async def test_get_agent_factory():
    llm = MockLLM()
    agent = get_agent("risk_officer", llm=llm)
    assert isinstance(agent, RiskOfficer)
    result = await agent.execute("Check VaR limits")
    assert result.answer.risks is not None


@pytest.mark.asyncio
async def test_api_ask_endpoint_with_mock(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import terminal_agents as ep

    mock = MockLLM()

    def _router():
        return LLMRouter([mock])

    monkeypatch.setattr(ep, "build_default_router", _router)

    app = FastAPI()
    app.include_router(ep.router, prefix="/api/v1")
    from app.core.deps import get_current_user_email

    app.dependency_overrides[get_current_user_email] = lambda: "user@example.com"
    client = TestClient(app)

    r = client.get("/api/v1/terminal/agents")
    assert r.status_code == 200
    assert "market_analyst" in r.json()["agents"]

    r2 = client.post(
        "/api/v1/terminal/agents/ask",
        json={"query": "Analyze AAPL", "agent_type": "market_analyst", "symbol": "AAPL"},
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["answer"]["confidence"] == 0.72

    r3 = client.get("/api/v1/terminal/agents/metrics")
    assert r3.status_code == 200
    assert r3.json()["total_predictions"] >= 1
