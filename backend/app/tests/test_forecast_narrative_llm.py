"""Tests for forecast LLM narrative enrichment (mocked httpx)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.forecast.forecast_narrative_llm import (
    apply_llm_narrative_to_disclosure,
    split_compact_narrative_layers,
    try_llm_forecast_narrative,
    try_llm_market_forecast_narrative,
)
from app.services.llm.llm_service import model_for_task


def test_split_compact_narrative_layers_russian():
    text = (
        "Вердикт - AAPL: реалистичный сценарий 52% — базовый план.\n"
        "Почему - Импульс нейтральный, ход около +1%.\n"
        "Что изменит взгляд - Сближение с оптимистичным сценарием.\n"
        "Действие - Лучше выждать подтверждения."
    )
    layers = split_compact_narrative_layers(text)
    assert layers is not None
    assert len(layers) == 4
    assert layers[0].startswith("Вердикт -")
    assert layers[1].startswith("Почему -")


def test_apply_llm_narrative_to_disclosure_replaces_paragraphs():
    llm = (
        "Вердикт - GAZP: пессимистичный 41%.\n"
        "Почему - Слабый импульс и повышенная волатильность.\n"
        "Что изменит взгляд - VIX ниже 20.\n"
        "Действие - Снизить размер."
    )
    base = {"paragraphs": ["Почему - vol regime умеренная, expansion 0%"], "engines_used": []}
    out = apply_llm_narrative_to_disclosure(base, llm)
    assert out["paragraphs"][0].startswith("Вердикт -")
    assert "vol regime" not in " ".join(out["paragraphs"])
    assert "LLMForecastNarrative" in out["engines_used"]


def test_task_names_route_to_client_chat(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_MODEL_CLIENT_CHAT", "test-model")
    monkeypatch.setattr(settings, "LLM_MODEL_BATCH", "test-model")
    assert model_for_task("inapp_chat") == "test-model"
    assert model_for_task("senior_analyst_chat") == "test-model"
    assert model_for_task("forecast_narrative") == "test-model"
    assert model_for_task("news_event_extraction") == "test-model"


@pytest.mark.asyncio
async def test_forecast_narrative_mocked(monkeypatch):
    from types import SimpleNamespace

    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "AITUNNEL_API_KEY", "sk-test")
    monkeypatch.setattr(settings, "FORECAST_MODE", "compact")

    hierarchy = SimpleNamespace(
        as_of="2026-01-01",
        calibrated_confidence=0.55,
        interval_forecast=SimpleNamespace(
            horizon_days=5,
            p10=-0.02,
            p90=0.04,
            rolling_volatility=0.2,
        ),
        distribution_forecast=SimpleNamespace(p50=0.01),
        action_forecast=SimpleNamespace(recommendation=SimpleNamespace(value="wait")),
        global_regime=SimpleNamespace(
            dominant_regime="risk_off",
            confidence=0.6,
        ),
        scenario_forecast=SimpleNamespace(
            scenarios=[
                SimpleNamespace(
                    label_ru="реалистичный сценарий",
                    name="realistic",
                    probability=0.52,
                    expected_impact=0.01,
                )
            ]
        ),
        risk_forecast=SimpleNamespace(plain_language_summary="Умеренный риск."),
    )

    mock_resp = AsyncMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json = lambda: {
        "choices": [{"message": {"content": "Краткое резюме по AAPL с учётом режима risk_off."}}]
    }
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.llm.llm_service.httpx.AsyncClient", return_value=mock_client):
        out = await try_llm_forecast_narrative(
            symbol="AAPL",
            hierarchy=hierarchy,
            disclosure={"paragraphs": ["Тестовый абзац сценария."]},
        )
    assert out and "AAPL" in out
    body = mock_client.post.call_args[1]["json"]
    assert body["model"] == model_for_task("forecast_narrative")
    assert body.get("reasoning_effort") == "none"
    assert body["temperature"] == 0.45
    assert body["max_tokens"] == 420
    system = body["messages"][0]["content"]
    user = body["messages"][1]["content"]
    assert "FORECAST COMPACT MODE" in system
    assert "Вердикт -" in system
    assert "Почему -" in system
    assert "vol regime" in system
    assert "P10 -2.0%, P50 +1.0%, P90 +4.0%" in user
    assert "реалистичный сценарий: 52%" in user
    assert "90–120 слов" in user or "90-120" in user


@pytest.mark.asyncio
async def test_market_forecast_narrative_mocked(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "AITUNNEL_API_KEY", "sk-test")
    monkeypatch.setattr(settings, "FORECAST_MODE", "compact")

    mock_resp = AsyncMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json = lambda: {"choices": [{"message": {"content": "Рынок в режиме осторожности."}}]}
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.llm.llm_service.httpx.AsyncClient", return_value=mock_client):
        out = await try_llm_market_forecast_narrative(
            disclosure={
                "paragraphs": ["Лидирует реалистичный сценарий."],
                "top_scenario": "realistic",
                "top_probability": 0.61,
                "breakdown": {"realistic": 0.61, "pessimistic": 0.24},
            },
            global_regime={"dominant_regime": "neutral", "confidence": 0.58},
            macro_indicators={"vix": 18.0, "cpi": 3.1, "dxy": 101.0},
            market_outlook=[
                {
                    "title": "Глобальный макро-режим",
                    "what_happens": "Нейтральный режим с умеренной волатильностью.",
                }
            ],
            sector_rotation=[
                {
                    "sector": "technology",
                    "sector_ru": "технологии",
                    "rotation_flag": "sectors_strengthening",
                }
            ],
            market_prediction_summary={
                "paragraphs": ["Сводный прогноз построен на GlobalMacroRegimeEngine."],
                "confidence_pct": 63.0,
            },
        )
    assert out and "осторож" in out.lower()
    body = mock_client.post.call_args[1]["json"]
    system = body["messages"][0]["content"]
    user = body["messages"][1]["content"]
    assert body["temperature"] == 0.45
    assert body["max_tokens"] == 900
    assert "человеческим языком" in user or "картину рынка" in system.lower() or "обычного человека" in system
    assert "GlobalMacroRegimeEngine" in system or "без имён внутренних" in user or "Запрещены" in system
    assert "Макро: vix=18.0, cpi=3.1, dxy=101.0" in user
    assert "Market outlook points" in user
    assert "Sector rotation" in user
    assert "Черновик сводки" in user


@pytest.mark.asyncio
@pytest.mark.skipif(
    not __import__("os").environ.get("AITUNNEL_API_KEY"),
    reason="Live AITUNNEL call — set AITUNNEL_API_KEY",
)
async def test_live_llm_smoke():
    from app.core.config import settings

    if not settings.AITUNNEL_API_KEY:
        pytest.skip("AITUNNEL_API_KEY not in settings")
    from app.services.llm.llm_service import LLMService

    text = await LLMService.complete(
        "inapp_chat",
        "В одном предложении: что такое beta акции?",
        system="Отвечай кратко по-русски.",
        max_tokens=120,
    )
    assert len(text) > 10
