"""Regression: paper mode must never submit real broker orders (Bybit, legacy T-Bank)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.execution.adapter import (
    OrderRequest,
    PaperExecutor,
    _RoutingExecutor,
    get_executor,
    requires_broker_paper_simulation,
)
from app.services.execution.guard import ManualOrderExecutionContext
from app.services.execution.providers.bridge import ExecutionProviderExecutor, wrap_provider
from app.services.execution.providers.bybit_tokenized import BybitTokenizedEquityProvider
from app.services.execution.providers.mock import MockExecutionProvider
from app.services.execution.providers.registry import ExecutionMode, get_execution_provider_for_user
from app.services.trading_keys.resolver import UserTradingKeyNotFound
from app.services.trading_keys.user_executor import get_user_executor


MAINNET_BYBIT_CREDS = {
    "api_key": "paper-guard-test-key",
    "api_secret": "paper-guard-test-secret",
    "base_url": "https://api.bybit.com",
}


def _manual_order_request(ticker: str = "AAPL") -> OrderRequest:
    return OrderRequest(
        ticker=ticker,
        side="buy",
        qty=1.0,
        order_type="market",
        manual_order_context=ManualOrderExecutionContext(manual_order_id="mo-guard-1"),
    )


@pytest.mark.parametrize(
    ("live_enabled", "confirmation", "account_mode", "expected"),
    [
        (False, "", "live", True),
        (False, "", "paper", True),
        (True, "I_UNDERSTAND_THE_RISKS", "paper", True),
        (True, "I_UNDERSTAND_THE_RISKS", "live", False),
    ],
)
def test_requires_broker_paper_simulation_matrix(
    monkeypatch: pytest.MonkeyPatch,
    live_enabled: bool,
    confirmation: str,
    account_mode: str,
    expected: bool,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "LIVE_TRADING_ENABLED", live_enabled)
    monkeypatch.setattr(settings, "LIVE_TRADING_CONFIRMATION", confirmation)
    monkeypatch.setattr(settings, "PAPER_TRADING_ENABLED", True)
    assert requires_broker_paper_simulation(account_mode) is expected


@pytest.mark.asyncio
async def test_paper_account_mode_returns_paper_executor_for_tokenized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "LIVE_TRADING_ENABLED", True)
    monkeypatch.setattr(settings, "LIVE_TRADING_CONFIRMATION", "I_UNDERSTAND_THE_RISKS")
    monkeypatch.setattr(settings, "PAPER_TRADING_ENABLED", True)

    db = AsyncMock()
    with patch(
        "app.services.trading_keys.user_executor.user_has_full_trading_grant",
        new=AsyncMock(return_value=False),
    ), patch(
        "app.services.trading_keys.user_executor.get_execution_provider_for_user",
        new=AsyncMock(side_effect=AssertionError("must not build live provider")),
    ):
        executor = await get_user_executor(
            db,
            user_id="u-paper-guard",
            ticker="AAPL",
            account_mode="paper",
        )

    assert isinstance(executor, PaperExecutor)


@pytest.mark.asyncio
async def test_registry_paper_mode_skips_credential_lookup() -> None:
    db = AsyncMock()
    with patch(
        "app.services.execution.providers.registry.get_tokenized_equity_credentials",
        new=AsyncMock(side_effect=AssertionError("must not load credentials in paper mode")),
    ):
        provider, mode = await get_execution_provider_for_user(
            db,
            user_id="u-paper-guard",
            ticker="AAPL",
            account_mode="paper",
        )

    assert isinstance(provider, MockExecutionProvider)
    assert mode is ExecutionMode.MOCK


@pytest.mark.asyncio
async def test_bridge_blocks_bybit_place_order_when_paper() -> None:
    provider = BybitTokenizedEquityProvider(
        api_key=MAINNET_BYBIT_CREDS["api_key"],
        api_secret=MAINNET_BYBIT_CREDS["api_secret"],
        base_url=MAINNET_BYBIT_CREDS["base_url"],
    )
    provider.place_order = AsyncMock(side_effect=AssertionError("must not call real Bybit API"))

    executor = ExecutionProviderExecutor(provider, mode="live", account_mode="paper")
    result = await executor.submit_order(_manual_order_request())

    assert result.status == "rejected"
    assert result.error == "Live trading not unlocked"
    assert result.raw.get("simulated_block") is True
    provider.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_paper_executor_submit_never_calls_bybit_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "LIVE_TRADING_ENABLED", False)
    monkeypatch.setattr(settings, "LIVE_TRADING_CONFIRMATION", "")
    monkeypatch.setattr(settings, "PAPER_TRADING_ENABLED", True)

    async def fake_quote(_ticker: str) -> dict[str, float]:
        return {"price": 150.0}

    monkeypatch.setattr(
        "app.services.market_data.client.get_latest_quote_resolved",
        fake_quote,
    )

    db = AsyncMock()
    bundle = MagicMock()
    bundle.provider_type = "bybit"
    bundle.credentials = MAINNET_BYBIT_CREDS

    with patch(
        "app.services.execution.providers.bybit_tokenized.BybitTokenizedEquityProvider._request",
        new=AsyncMock(side_effect=AssertionError("must not call Bybit HTTP")),
    ), patch(
        "app.services.trading_keys.user_executor.user_has_full_trading_grant",
        new=AsyncMock(return_value=False),
    ), patch(
        "app.services.trading_keys.user_executor.get_execution_provider_for_user",
        new=AsyncMock(side_effect=AssertionError("must not resolve live provider")),
    ):
        executor = await get_user_executor(
            db,
            user_id="u-paper-guard",
            ticker="AAPL",
            account_mode="paper",
        )
        result = await executor.submit_order(_manual_order_request())

    assert isinstance(executor, PaperExecutor)
    assert result.status == "filled"
    assert result.broker_order_id is not None
    assert str(result.broker_order_id).startswith("paper-")


@pytest.mark.asyncio
async def test_live_unlocked_live_slot_can_build_bybit_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "LIVE_TRADING_ENABLED", True)
    monkeypatch.setattr(settings, "LIVE_TRADING_CONFIRMATION", "I_UNDERSTAND_THE_RISKS")
    monkeypatch.setattr(settings, "PAPER_TRADING_ENABLED", True)

    db = AsyncMock()
    bundle = MagicMock()
    bundle.provider_type = "bybit"
    bundle.credentials = MAINNET_BYBIT_CREDS

    with patch(
        "app.services.execution.providers.registry.get_tokenized_equity_credentials",
        new=AsyncMock(return_value=bundle),
    ):
        provider, mode = await get_execution_provider_for_user(
            db,
            user_id="u-live",
            ticker="AAPL",
            account_mode="live",
        )

    assert isinstance(provider, BybitTokenizedEquityProvider)
    assert mode is ExecutionMode.LIVE
    wrapped = wrap_provider(provider, mode=mode.value, account_mode="live")
    assert isinstance(wrapped, ExecutionProviderExecutor)


@pytest.mark.asyncio
async def test_live_tokenized_without_key_does_not_use_demo_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "LIVE_TRADING_ENABLED", True)
    monkeypatch.setattr(settings, "LIVE_TRADING_CONFIRMATION", "I_UNDERSTAND_THE_RISKS")
    monkeypatch.setattr(settings, "PAPER_TRADING_ENABLED", True)

    db = AsyncMock()
    with patch(
        "app.services.execution.providers.registry.get_tokenized_equity_credentials",
        new=AsyncMock(side_effect=UserTradingKeyNotFound("no tokenized equity key")),
    ):
        with pytest.raises(UserTradingKeyNotFound):
            await get_execution_provider_for_user(
                db,
                user_id="u-live",
                ticker="AAPL",
                account_mode="live",
            )


def _moex_order_request(ticker: str = "SBER") -> OrderRequest:
    return OrderRequest(
        ticker=ticker,
        side="buy",
        qty=10.0,
        order_type="market",
        manual_order_context=ManualOrderExecutionContext(manual_order_id="mo-moex-guard-1"),
    )


@pytest.mark.asyncio
async def test_routing_executor_moex_uses_paper_when_live_locked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "LIVE_TRADING_ENABLED", False)
    monkeypatch.setattr(settings, "LIVE_TRADING_CONFIRMATION", "")
    monkeypatch.setattr(settings, "PAPER_TRADING_ENABLED", True)

    async def fake_quote(_ticker: str) -> dict[str, float]:
        return {"price": 280.0}

    monkeypatch.setattr(
        "app.services.market_data.client.get_latest_quote_resolved",
        fake_quote,
    )

    tinkoff = AsyncMock()
    tinkoff.submit_order = AsyncMock(side_effect=AssertionError("must not call real T-Bank API"))
    router = _RoutingExecutor(tinkoff=tinkoff, paper=PaperExecutor(), alpaca=AsyncMock())

    result = await router.submit_order(_moex_order_request("SBER"))

    assert result.status == "filled"
    assert str(result.broker_order_id).startswith("paper-")
    tinkoff.submit_order.assert_not_called()


@pytest.mark.asyncio
async def test_get_executor_legacy_moex_path_paper_guard_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "LIVE_TRADING_ENABLED", False)
    monkeypatch.setattr(settings, "LIVE_TRADING_CONFIRMATION", "")
    monkeypatch.setattr(settings, "PAPER_TRADING_ENABLED", True)
    monkeypatch.setenv("TINKOFF_API_TOKEN", "legacy-env-token")

    async def fake_quote(_ticker: str) -> dict[str, float]:
        return {"price": 280.0}

    monkeypatch.setattr(
        "app.services.market_data.client.get_latest_quote_resolved",
        fake_quote,
    )

    with patch(
        "app.services.broker.tinkoff_orders.TinkoffExecutor.submit_order",
        new=AsyncMock(side_effect=AssertionError("must not call real T-Bank API")),
    ):
        executor = get_executor()
        assert isinstance(executor, _RoutingExecutor)
        result = await executor.submit_order(_moex_order_request("USD000UTSTOM"))

    assert result.status == "filled"
    assert str(result.broker_order_id).startswith("paper-")


@pytest.mark.asyncio
async def test_routing_executor_moex_uses_tinkoff_when_live_unlocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "LIVE_TRADING_ENABLED", True)
    monkeypatch.setattr(settings, "LIVE_TRADING_CONFIRMATION", "I_UNDERSTAND_THE_RISKS")
    monkeypatch.setattr(settings, "PAPER_TRADING_ENABLED", True)

    tinkoff = AsyncMock()
    tinkoff.submit_order = AsyncMock(
        return_value=MagicMock(status="submitted", broker_order_id="tb-live-1")
    )
    router = _RoutingExecutor(tinkoff=tinkoff, paper=PaperExecutor(), alpaca=AsyncMock())

    await router.submit_order(_moex_order_request("SBER"))

    tinkoff.submit_order.assert_awaited_once()

