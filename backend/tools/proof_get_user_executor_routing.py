#!/usr/bin/env python3
"""Proof: get_user_executor logs provider_type + execution_venue (no live orders or keys)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch


async def _run_once(provider: str, logs: list[dict]) -> None:
    from app.services.trading_keys.user_executor import get_user_executor, TradingKeyRequiredError

    db = AsyncMock()
    with patch(
        "app.services.trading_keys.user_executor.use_local_paper_simulation",
        return_value=False,
    ):
        with patch(
            "app.services.trading_keys.user_executor._preferred_tokenized_provider",
            new_callable=AsyncMock,
            return_value=provider,
        ):
            with patch(
                "app.services.trading_keys.user_executor.get_execution_provider_for_user",
                new_callable=AsyncMock,
                side_effect=Exception("no keys — routing proof only"),
            ):
                with patch(
                    "app.services.trading_keys.user_executor.logger.info",
                    side_effect=lambda event, **kw: logs.append({"event": event, **kw}),
                ):
                    try:
                        await get_user_executor(
                            db,
                            user_id="proof-user",
                            ticker="AAPL",
                            account_mode="live",
                        )
                    except Exception:
                        pass


async def main() -> None:
    logs: list[dict] = []
    await _run_once("bybit", logs)
    await _run_once("mexc", logs)

    bybit = next((x for x in logs if x.get("provider_type") == "bybit"), None)
    mexc = next((x for x in logs if x.get("provider_type") == "mexc"), None)
    assert bybit and bybit.get("event") == "get_user_executor", bybit
    assert mexc and mexc.get("event") == "get_user_executor", mexc
    assert bybit.get("execution_venue") == "tokenized_equity"
    assert mexc.get("execution_venue") == "tokenized_equity"
    print("ROUTING_LOG_OK bybit", bybit.get("execution_venue"))
    print("ROUTING_LOG_OK mexc", mexc.get("execution_venue"))


if __name__ == "__main__":
    asyncio.run(main())
