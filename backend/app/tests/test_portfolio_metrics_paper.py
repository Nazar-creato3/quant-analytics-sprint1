"""Paper mode must use internal ledger, not platform Alpaca account."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.portfolio import PortfolioMetricsOut
from app.services.portfolio.metrics import build_portfolio_metrics


@pytest.mark.asyncio
async def test_paper_mode_skips_platform_alpaca():
    alpaca_stub = PortfolioMetricsOut(
        trading_usd=0.0,
        balance_usd=55.0,
        total_usd=55.0,
        mode="live",
        source="alpaca",
        as_of="2026-09-07T00:00:00+00:00",
    )
    internal_stub = PortfolioMetricsOut(
        trading_usd=100.0,
        balance_usd=286.0,
        total_usd=386.0,
        mode="paper",
        source="internal",
        as_of="2026-09-07T00:00:01+00:00",
    )

    with (
        patch("app.services.portfolio.metrics.settings") as mock_settings,
        patch(
            "app.services.portfolio.metrics._alpaca_metrics",
            new_callable=AsyncMock,
            return_value=alpaca_stub,
        ) as mock_alpaca,
        patch(
            "app.services.portfolio.metrics._internal_metrics",
            new_callable=AsyncMock,
            return_value=internal_stub,
        ) as mock_internal,
        patch(
            "app.services.portfolio.metrics._user_portfolio_size",
            new_callable=AsyncMock,
            return_value=55.0,
        ),
        patch(
            "app.services.portfolio.user_scope.get_user_by_email",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.services.trading_keys.user_executor.resolve_user_account_mode",
            new_callable=AsyncMock,
            return_value="paper",
        ),
    ):
        mock_settings.PAPER_TRADING_ENABLED = True
        mock_settings.live_trading_unlocked = True
        mock_settings.ALPACA_API_KEY = "key"
        mock_settings.ALPACA_SECRET_KEY = "secret"

        result = await build_portfolio_metrics("user@test.com", AsyncMock())

    mock_alpaca.assert_not_called()
    mock_internal.assert_awaited_once()
    assert result.total_usd == 386.0
    assert result.mode == "paper"
    assert result.source == "internal"
