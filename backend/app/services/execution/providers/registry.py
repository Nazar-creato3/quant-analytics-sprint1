"""ExecutionProvider factory — resolves mock vs live per user/symbol."""
from __future__ import annotations

from enum import Enum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.execution.adapter import requires_broker_paper_simulation
from app.services.execution.providers.base import ExecutionProvider
from app.services.execution.providers.factory import build_mock_provider, build_tokenized_equity_provider
from app.services.execution.providers.mock import MockExecutionProvider
from app.services.execution.symbol_mapping import resolve_symbol_route
from app.services.trading_keys.resolver import UserTradingKeyNotFound, get_active_user_credentials
from app.services.trading_keys.tokenized_resolver import get_tokenized_equity_credentials

logger = get_logger(__name__)


class ExecutionMode(str, Enum):
    MOCK = "mock"
    LIVE = "live"


async def get_execution_provider_for_user(
    db: AsyncSession,
    *,
    user_id: str,
    ticker: str,
    account_mode: str = "live",
    force_mock: bool = False,
    preferred_provider: str | None = None,
) -> tuple[ExecutionProvider, ExecutionMode]:
    """Return provider + mode. Tokenized equities default to mock when no key."""
    route = resolve_symbol_route(ticker, provider_type=preferred_provider or "bybit")

    if force_mock or route.execution_venue == "mock":
        return build_mock_provider(user_id=user_id), ExecutionMode.MOCK

    if route.execution_venue == "tokenized_equity":
        if requires_broker_paper_simulation(account_mode):
            logger.info(
                "Tokenized equity paper mode — mock provider",
                user_id=user_id,
                ticker=ticker,
                account_mode=account_mode,
            )
            return MockExecutionProvider(user_id=user_id), ExecutionMode.MOCK
        try:
            bundle = await get_tokenized_equity_credentials(
                db, user_id=user_id, account_mode=account_mode
            )
            provider = build_tokenized_equity_provider(
                bundle.provider_type,
                bundle.credentials,
            )
            return provider, ExecutionMode.LIVE
        except UserTradingKeyNotFound:
            logger.info("No tokenized equity key — refuse live mock", user_id=user_id, ticker=ticker)
            raise

    # Crypto / MOEX require keys — no silent mock
    venue = route.execution_venue
    try:
        creds = await get_active_user_credentials(
            db,
            user_id=user_id,
            venue=venue,
            account_mode=account_mode,
            action="order_execution",
        )
    except UserTradingKeyNotFound:
        raise

    payload = creds.credentials
    if venue == "binance":
        from app.services.trading_keys.executors import BinanceUserExecutor  # noqa: F401

        raise UserTradingKeyNotFound(user_id=user_id, venue=venue)  # wired via BinanceUserExecutor in user_executor
    raise UserTradingKeyNotFound(user_id=user_id, venue=venue)


def get_execution_provider(
    *,
    kind: str,
    credentials: dict[str, Any] | None = None,
    user_id: str | None = None,
) -> ExecutionProvider:
    """Direct instantiation for validation/health checks."""
    if kind == "mock":
        return build_mock_provider(user_id=user_id)
    if kind in ("bybit", "bybit_tokenized"):
        return build_tokenized_equity_provider("bybit", credentials or {})
    if kind in ("mexc", "mexc_tokenized"):
        return build_tokenized_equity_provider("mexc", credentials or {})
    raise ValueError(f"Unknown provider kind: {kind}")
