import pytest
from unittest.mock import AsyncMock, patch

from app.services.terminal_platform.market.index_fallbacks import fetch_index_quote_with_fallbacks


@pytest.mark.asyncio
async def test_index_fallback_uses_etf_alias() -> None:
    with (
        patch(
            "app.services.terminal_platform.market.index_fallbacks.fetch_cboe_vix",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.services.terminal_platform.market.index_fallbacks.fetch_keyed_equity_quote",
            new_callable=AsyncMock,
            return_value={
                "symbol": "SPY",
                "status": "ok",
                "price": 500.0,
                "change": 1.0,
                "change_pct": 0.2,
                "provider": "finnhub",
                "as_of": "2026-08-09T00:00:00+00:00",
            },
        ),
    ):
        q = await fetch_index_quote_with_fallbacks("^GSPC", try_native=False)
    assert q["status"] == "ok"
    assert q["price"] == 500.0
    assert "SPY" in (q.get("provider") or "")


@pytest.mark.asyncio
async def test_vix_uses_vol_etf_when_cboe_down() -> None:
    with (
        patch(
            "app.services.terminal_platform.market.index_fallbacks.fetch_cboe_vix",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.services.terminal_platform.market.index_fallbacks.fetch_keyed_equity_quote",
            new_callable=AsyncMock,
            return_value={
                "symbol": "VIXY",
                "status": "ok",
                "price": 19.5,
                "change_pct": 1.2,
                "provider": "finnhub",
                "as_of": "2026-08-09T00:00:00+00:00",
            },
        ),
    ):
        q = await fetch_index_quote_with_fallbacks("^VIX")
    assert q["status"] == "ok"
    assert q["price"] == 19.5
    assert "vol_etf_proxy" in (q.get("reason") or "")
