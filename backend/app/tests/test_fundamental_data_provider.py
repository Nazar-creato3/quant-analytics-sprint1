"""Tests for FundamentalDataProvider adapters."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.fundamental_data.disabled_provider import DisabledFundamentalDataProvider
from app.services.fundamental_data.factory import get_fundamental_data_provider, reset_fundamental_data_provider_cache
from app.services.fundamental_data.openbb_adapter import OpenBBFundamentalDataProvider


@pytest.fixture(autouse=True)
def _clear_provider_cache():
    reset_fundamental_data_provider_cache()
    yield
    reset_fundamental_data_provider_cache()


class TestDisabledProvider:
    @pytest.mark.asyncio
    async def test_sec_filings_returns_source_disabled(self):
        provider = DisabledFundamentalDataProvider()
        assert provider.source_enabled is False
        result = await provider.get_sec_filings("AAPL")
        assert result.success is False
        assert result.error_code == "SOURCE_DISABLED"
        assert result.source_enabled is False
        assert "недоступны" in (result.error or "").lower() or "недоступны" in (result.error or "")

    @pytest.mark.asyncio
    async def test_finra_returns_source_disabled(self):
        provider = DisabledFundamentalDataProvider()
        result = await provider.get_finra_short_interest("AAPL")
        assert result.success is False
        assert result.error_code == "SOURCE_DISABLED"


class TestOpenBBAdapter:
    @pytest.mark.asyncio
    async def test_sec_filings_success(self):
        provider = OpenBBFundamentalDataProvider("http://sidecar:6900", timeout_seconds=2.0)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "symbol": "AAPL",
            "filings": [
                {
                    "symbol": "AAPL",
                    "form_type": "10-K",
                    "filing_date": "2024-11-01",
                    "link": "https://www.sec.gov/example",
                }
            ],
            "count": 1,
        }
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.fundamental_data.openbb_adapter.httpx.AsyncClient", return_value=mock_client):
            result = await provider.get_sec_filings("AAPL")

        assert result.success is True
        assert result.data["count"] == 1
        assert result.data["filings"][0]["form_type"] == "10-K"
        assert result.source_enabled is True

    @pytest.mark.asyncio
    async def test_finra_timeout(self):
        provider = OpenBBFundamentalDataProvider("http://sidecar:6900", timeout_seconds=0.1)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.fundamental_data.openbb_adapter.httpx.AsyncClient", return_value=mock_client):
            result = await provider.get_finra_short_interest("AAPL")

        assert result.success is False
        assert result.error_code == "TIMEOUT"


class TestFactory:
    def test_factory_always_composite(self, monkeypatch):
        monkeypatch.setenv("ENABLE_OPENBB_SOURCE", "false")
        from app.core.config import get_settings
        from app.services.fundamental_data.composite import CompositeRegulatoryProvider

        get_settings.cache_clear()
        reset_fundamental_data_provider_cache()
        provider = get_fundamental_data_provider()
        assert isinstance(provider, CompositeRegulatoryProvider)
        get_settings.cache_clear()

    def test_factory_sidecar_flag_does_not_disable_native(self, monkeypatch):
        monkeypatch.setenv("ENABLE_OPENBB_SOURCE", "true")
        monkeypatch.setenv("OPENBB_SERVICE_URL", "http://localhost:6900")
        from app.core.config import get_settings
        from app.services.fundamental_data.composite import CompositeRegulatoryProvider

        get_settings.cache_clear()
        reset_fundamental_data_provider_cache()
        provider = get_fundamental_data_provider()
        assert isinstance(provider, CompositeRegulatoryProvider)
        assert provider._sidecar is not None
        get_settings.cache_clear()
