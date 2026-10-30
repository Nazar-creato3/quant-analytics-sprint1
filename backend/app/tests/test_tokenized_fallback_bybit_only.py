"""Bybit-only tokenized fallback — no alternate provider suggestions."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_fallback_never_suggests_switch_bybit_only() -> None:
    from app.services.trading_keys.resolver import UserTradingKeyNotFound
    from app.services.trading_keys.tokenized_fallback import check_tokenized_fallback

    db = AsyncMock()
    with patch(
        "app.services.trading_keys.tokenized_fallback.get_tokenized_equity_credentials",
        side_effect=UserTradingKeyNotFound("no key"),
    ):
        out = await check_tokenized_fallback(db, user_id="u1", email="test@example.com")

    assert out.primary_provider == "bybit"
    assert out.alternate_provider is None
    assert out.alternate_connected is False
    assert out.suggest_switch is False
    assert out.message is None
