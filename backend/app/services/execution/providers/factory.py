"""Instantiate ExecutionProvider from provider_type + credentials."""
from __future__ import annotations

from typing import Any

from app.services.execution.providers.base import ExecutionProvider
from app.services.execution.providers.bybit_tokenized import BybitTokenizedEquityProvider
from app.services.execution.providers.mock import MockExecutionProvider
from app.services.execution.providers.mexc_tokenized import MexcTokenizedEquityProvider
from app.services.execution.tokenized_provider_type import TokenizedProvider


def build_tokenized_equity_provider(
    provider_type: str,
    credentials: dict[str, Any],
) -> ExecutionProvider:
    kind = TokenizedProvider.normalize(provider_type)
    api_key = credentials.get("api_key", "")
    api_secret = credentials.get("api_secret", "")
    base_url = credentials.get("base_url")
    if kind == TokenizedProvider.MEXC:
        return MexcTokenizedEquityProvider(
            api_key=api_key,
            api_secret=api_secret,
            base_url=base_url,
        )
    return BybitTokenizedEquityProvider(
        api_key=api_key,
        api_secret=api_secret,
        base_url=base_url,
    )


def build_mock_provider(*, user_id: str | None = None) -> ExecutionProvider:
    return MockExecutionProvider(user_id=user_id)
