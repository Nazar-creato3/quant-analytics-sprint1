"""GigaChat provider: auth token exchange, tool-call bridge, LLMService routing."""
from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import settings
from app.services.llm import gigachat
from app.services.llm.llm_service import LLMService, llm_enabled, model_for_task


@pytest.fixture
def giga(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gigachat")
    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_ONPREM", False)
    monkeypatch.setattr(settings, "GIGACHAT_AUTH_KEY", "a2V5OnNlY3JldA==")
    gigachat._token.update(value="", expires=0.0)
    calls: list[httpx.Request] = []
    replies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/oauth"):
            return httpx.Response(200, json={"access_token": "tok-1", "expires_at": 9_999_999_999_000})
        return httpx.Response(200, json=replies.pop(0))

    real = httpx.AsyncClient

    def client(*a, **kw):
        kw.pop("verify", None)
        return real(*a, transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(gigachat.httpx, "AsyncClient", client)
    return calls, replies


def test_enabled_and_model(giga) -> None:
    assert llm_enabled()
    assert model_for_task("inapp_chat") == settings.GIGACHAT_MODEL


@pytest.mark.asyncio
async def test_plain_completion_gets_token_then_answers(giga) -> None:
    calls, replies = giga
    replies.append({"choices": [{"message": {"role": "assistant", "content": "Риск портфеля умеренный."}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    out = await LLMService.complete("inapp_chat", "Оцени риск", system="Ты аналитик")
    assert out == "Риск портфеля умеренный."
    auth, chat = calls
    assert auth.headers["Authorization"] == "Basic a2V5OnNlY3JldA==" and auth.headers.get("RqUID")
    assert b"scope=GIGACHAT_API_PERS" in auth.content
    assert chat.headers["Authorization"] == "Bearer tok-1"
    body = json.loads(chat.content)
    assert body["model"] == settings.GIGACHAT_MODEL and "reasoning_effort" not in body
    assert body["messages"][0] == {"role": "system", "content": "Ты аналитик"}


@pytest.mark.asyncio
async def test_tool_call_round_trip(giga) -> None:
    calls, replies = giga
    tools = [{"type": "function", "function": {"name": "portfolio_risk", "description": "VaR", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}}}}]
    replies.append({"choices": [{"message": {"role": "assistant", "content": "", "function_call": {"name": "portfolio_risk", "arguments": {"ticker": "SBER"}}, "functions_state_id": "st-1"}, "finish_reason": "function_call"}]})
    msg = await LLMService.complete_with_tools("inapp_chat", [{"role": "user", "content": "риск SBER?"}], tools=tools)
    tc = msg["tool_calls"][0]
    assert tc["function"]["name"] == "portfolio_risk" and json.loads(tc["function"]["arguments"]) == {"ticker": "SBER"}
    sent = json.loads(calls[-1].content)
    assert sent["functions"][0]["name"] == "portfolio_risk" and sent["function_call"] == "auto"

    history = [{"role": "user", "content": "риск SBER?"}, msg, {"role": "tool", "tool_call_id": tc["id"], "content": "VaR 4.1%"}]
    replies.append({"choices": [{"message": {"role": "assistant", "content": "VaR 4,1%."}}]})
    final = await LLMService.complete_with_tools("inapp_chat", history, tools=tools)
    assert final["content"] == "VaR 4,1%."
    sent = json.loads(calls[-1].content)["messages"]
    assert sent[1]["function_call"] == {"name": "portfolio_risk", "arguments": {"ticker": "SBER"}}
    assert sent[1]["functions_state_id"] == "st-1"
    assert sent[2] == {"role": "function", "name": "portfolio_risk", "content": json.dumps({"result": "VaR 4.1%"}, ensure_ascii=False)}
    assert sum(1 for c in calls if c.url.path.endswith("/oauth")) == 1  # token reused
