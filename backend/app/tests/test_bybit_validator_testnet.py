"""Tests for Bybit testnet vs mainnet key validation errors."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.trading_keys.bybit_validator import validate_bybit_key


def _mock_response(*, status_code: int, text: str) -> httpx.Response:
    req = httpx.Request("GET", "https://api-testnet.bybit.com/v5/account/wallet-balance")
    return httpx.Response(status_code=status_code, text=text, request=req)


@pytest.mark.asyncio
async def test_mainnet_key_on_testnet_empty_401_is_actionable_error() -> None:
    resp = _mock_response(status_code=401, text="")
    client = AsyncMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.trading_keys.bybit_validator.httpx.AsyncClient", return_value=client):
        result = await validate_bybit_key(
            api_key="testnet-key",
            api_secret="testnet-secret",
            base_url="https://api-testnet.bybit.com",
        )

    assert result.ok is False
    assert result.error is not None
    assert "testnet.bybit.com" in result.error
    assert "mainnet" in result.error.lower() or "Mainnet" in result.error
    assert "Expecting value" not in result.error


@pytest.mark.asyncio
async def test_testnet_invalid_api_key_json_message() -> None:
    body = '{"retCode":10003,"retMsg":"API key is invalid.","result":{}}'
    resp = _mock_response(status_code=200, text=body)
    client = AsyncMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.trading_keys.bybit_validator.httpx.AsyncClient", return_value=client):
        result = await validate_bybit_key(
            api_key="bad-key",
            api_secret="bad-secret",
            base_url="https://api-testnet.bybit.com",
        )

    assert result.ok is False
    assert result.error is not None
    assert "testnet.bybit.com" in result.error
