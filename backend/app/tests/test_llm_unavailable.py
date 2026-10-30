"""Defensive AITunnel / LLM error handling."""
from __future__ import annotations

import pytest

from app.services.llm.errors import AITUNNEL_UNAVAILABLE_RU, AITunnelUnavailableError
from app.services.llm.llm_service import _parse_completion_response


def test_parse_completion_raises_on_null_body() -> None:
    with pytest.raises(AITunnelUnavailableError, match=AITUNNEL_UNAVAILABLE_RU):
        _parse_completion_response(None)


def test_parse_completion_raises_on_empty_choices() -> None:
    with pytest.raises(AITunnelUnavailableError, match=AITUNNEL_UNAVAILABLE_RU):
        _parse_completion_response({"choices": []})


def test_parse_completion_raises_on_bad_message_type() -> None:
    with pytest.raises(AITunnelUnavailableError, match=AITUNNEL_UNAVAILABLE_RU):
        _parse_completion_response({"choices": [{"message": "not-a-dict"}]})


def test_parse_completion_returns_content() -> None:
    text = _parse_completion_response(
        {"choices": [{"message": {"content": "  hello  "}}]}
    )
    assert text == "hello"


def test_friendly_forecast_detail_maps_aitunnel() -> None:
    from app.api.v1.endpoints.forecast import _friendly_forecast_detail

    exc = AITunnelUnavailableError(f"{AITUNNEL_UNAVAILABLE_RU}: HTTP 402")
    detail = _friendly_forecast_detail(exc, "AAPL")
    assert "HTTP 402" not in detail and "Tunnel" not in detail
    assert "недоступно" in detail


def test_friendly_forecast_detail_maps_typeerror() -> None:
    from app.api.v1.endpoints.forecast import _friendly_forecast_detail

    detail = _friendly_forecast_detail(TypeError("'NoneType' object is not subscriptable"), "MSFT")
    assert "Пояснение ИИ временно недоступно" in detail
    assert "TypeError" not in detail
