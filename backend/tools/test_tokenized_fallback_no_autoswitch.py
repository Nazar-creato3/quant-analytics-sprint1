#!/usr/bin/env python3
"""Verify tokenized fallback never auto-switches provider."""
import asyncio
from unittest.mock import AsyncMock, patch


async def main() -> None:
    from app.services.trading_keys.resolver import UserTradingKeyNotFound
    from app.services.trading_keys.tokenized_fallback import check_tokenized_fallback

    db = AsyncMock()
    with patch(
        "app.services.trading_keys.tokenized_fallback.cache_get",
        new_callable=AsyncMock,
    ) as cache_get:
        cache_get.return_value = {"tokenized_equity_provider": "bybit"}
        with patch(
            "app.services.trading_keys.tokenized_fallback.get_tokenized_equity_credentials",
            side_effect=UserTradingKeyNotFound(),
        ):
            out = await check_tokenized_fallback(db, user_id="u1", email="test@example.com")
    assert out.suggest_switch is False, "must not suggest switch without alternate_connected"
    assert out.primary_provider == "bybit"
    print("FALLBACK_NO_AUTOSWITCH_OK", out.suggest_switch, out.primary_provider)


if __name__ == "__main__":
    asyncio.run(main())
