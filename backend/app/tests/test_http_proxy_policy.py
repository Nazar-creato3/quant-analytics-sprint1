"""Tests for selective foreign proxy + soft provider failure status."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.http_proxy import (
    foreign_https_proxy,
    host_must_be_direct,
    httpx_client_kwargs,
    httpx_ssl_verify,
    redacted_proxy_status,
)
from app.services.terminal_platform.base import DataProvider, DataProviderConfig
from app.services.terminal_platform.types import ProviderStatus


class _DummyProvider(DataProvider):
    async def fetch_ohlcv(self, *args, **kwargs):
        raise NotImplementedError

    async def fetch_quote(self, *args, **kwargs):
        raise NotImplementedError

    async def fetch_macro_series(self, *args, **kwargs):
        raise NotImplementedError

    async def fetch_fundamentals(self, *args, **kwargs):
        raise NotImplementedError

    async def fetch_news(self, *args, **kwargs):
        raise NotImplementedError


def test_moex_and_binance_hosts_are_direct():
    assert host_must_be_direct("iss.moex.com")
    assert host_must_be_direct("api.binance.com")
    assert host_must_be_direct("www.cbr.ru")
    assert host_must_be_direct("news.rbc.ru")
    assert not host_must_be_direct("data.alpaca.markets")
    assert not host_must_be_direct("api.polygon.io")


def test_httpx_kwargs_foreign_vs_direct():
    with patch("app.core.http_proxy._settings_proxy", return_value="http://u:p@212.8.249.134:11190"):
        foreign = httpx_client_kwargs(foreign=True)
        direct = httpx_client_kwargs(foreign=False)
    assert foreign["trust_env"] is False
    assert foreign["proxy"] == "http://u:p@212.8.249.134:11190"
    assert direct["trust_env"] is False
    assert direct["proxy"] is None


def test_redacted_proxy_status_never_includes_password():
    with patch(
        "app.core.http_proxy.foreign_https_proxy",
        return_value="http://secretuser:secretpass@212.8.249.134:11190",
    ):
        status = redacted_proxy_status()
    blob = str(status)
    assert "secretpass" not in blob
    assert "secretuser" not in blob
    assert status["foreign_proxy"] == "set"
    assert status["host"] == "212.8.249.134"
    assert status["port"] == 11190


def test_soft_unsupported_does_not_mark_degraded():
    provider = _DummyProvider(DataProviderConfig(name="moex_iss"))
    assert provider.status == ProviderStatus.ACTIVE
    result = provider._timed_failure(
        start=0.0,
        error="USO is not a MOEX ticker",
        error_code="UNSUPPORTED",
    )
    assert result.error_code == "UNSUPPORTED"
    assert provider.status == ProviderStatus.ACTIVE
    assert provider._last_error is None


def test_hard_failure_marks_degraded():
    provider = _DummyProvider(DataProviderConfig(name="alpaca", requires_api_key=False))
    result = provider._timed_failure(
        start=0.0,
        error="ConnectTimeout",
        error_code="PROVIDER_ERROR",
    )
    assert result.success is False
    assert provider.status == ProviderStatus.DEGRADED


def test_httpx_ssl_verify_uses_certifi_or_env(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    path = httpx_ssl_verify()
    assert isinstance(path, str) and len(path) > 0
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/custom/ca.pem")
    assert httpx_ssl_verify() == "/custom/ca.pem"
