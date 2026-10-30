"""Tests for AITUNNEL LLMService routing and responses."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.llm.llm_service import (
    LLMService,
    _extract_message_text,
    llm_base_url,
    model_for_task,
)


def test_model_for_task_client_vs_batch(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_MODEL_CLIENT_CHAT", "kimi-k3")
    monkeypatch.setattr(settings, "LLM_MODEL_BATCH", "kimi-test")
    assert model_for_task("inapp_chat") == "kimi-k3"
    assert model_for_task("senior_analyst_chat") == "kimi-k3"
    assert model_for_task("forecast_narrative") == "kimi-k3"
    assert model_for_task("news_event_extraction") == "kimi-test"


@pytest.mark.asyncio
async def test_llm_service_uses_aitunnel_base_url(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "AITUNNEL_API_KEY", "sk-test")
    monkeypatch.setattr(settings, "AITUNNEL_BASE_URL", "https://api.aitunnel.ru/v1")
    monkeypatch.setattr(settings, "LLM_MODEL_BATCH", "kimi-k3")

    mock_resp = AsyncMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json = lambda: {"choices": [{"message": {"content": "[]"}}]}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.llm.llm_service.httpx.AsyncClient", return_value=mock_client):
        out = await LLMService.complete("news_event_extraction", "hello")
        assert out == "[]"
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[0][0] == f"{llm_base_url()}/chat/completions"
        body = call_kwargs[1]["json"]
        assert body["model"] == model_for_task("news_event_extraction")


@pytest.mark.asyncio
async def test_llm_service_kimi_client_chat_task(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "AITUNNEL_API_KEY", "sk-test")
    monkeypatch.setattr(settings, "LLM_MODEL_CLIENT_CHAT", "kimi-k3")

    mock_resp = AsyncMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json = lambda: {"choices": [{"message": {"content": "[1] ok"}}]}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.llm.llm_service.httpx.AsyncClient", return_value=mock_client):
        out = await LLMService.complete("inapp_chat", "Q?", system="sys")
        assert out.startswith("[1]")
        body = mock_client.post.call_args[1]["json"]
        assert body["model"] == "kimi-k3"


def test_extract_message_text_from_reasoning_verdict_lines():
    message = {
        "content": "",
        "reasoning": (
            "Let me think...\n"
            "Вердикт - AAPL в режиме осторожности.\n"
            "Почему - Импульс слабый, ход около +1%.\n"
            "Что изменит взгляд - VIX ниже 18.\n"
            "Действие - Снизить размер позиции."
        ),
    }
    text = _extract_message_text(message)
    assert text.startswith("Вердикт -")
    assert "Действие -" in text


@pytest.mark.asyncio
async def test_forecast_narrative_disables_reasoning(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "AITUNNEL_API_KEY", "sk-test")
    monkeypatch.setattr(settings, "LLM_MODEL_CLIENT_CHAT", "kimi-k3")

    mock_resp = AsyncMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json = lambda: {
        "choices": [{"message": {"content": "Вердикт - ok"}, "finish_reason": "stop"}]
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.llm.llm_service.httpx.AsyncClient", return_value=mock_client):
        out = await LLMService.complete("forecast_narrative", "Q?")
        assert out.startswith("Вердикт")
        body = mock_client.post.call_args[1]["json"]
        assert body["reasoning_effort"] == "none"
