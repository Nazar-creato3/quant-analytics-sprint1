"""USD notional → true shares for a real order (RUB instruments)."""
import pytest

from app.services.market_data import fx_rates


@pytest.mark.asyncio
async def test_rub_share_count_uses_usd_rub(monkeypatch):
    async def quote(pair, force_refresh=False):
        assert pair == "USD000UTSTOM"
        return {"price": 80.0}

    monkeypatch.setattr("app.services.market_data.moex_currency.get_moex_currency_quote", quote)
    qty, k = await fx_rates.native_qty("SBER", 562.0, 300.0)
    # 562 USD = 44 960 RUB → 149.9 shares at 300 RUB (not 1.87).
    assert qty == pytest.approx(149.8667, rel=1e-4)
    assert k == pytest.approx(1 / 80)


@pytest.mark.asyncio
async def test_usd_instrument_unchanged():
    qty, k = await fx_rates.native_qty("AAPL", 600.0, 200.0)
    assert qty == pytest.approx(3.0) and k == 1.0


@pytest.mark.asyncio
async def test_no_rate_no_conversion(monkeypatch):
    async def quote(pair, force_refresh=False):
        return None

    monkeypatch.setattr("app.services.market_data.moex_currency.get_moex_currency_quote", quote)
    assert await fx_rates.native_qty("SBER", 562.0, 300.0) is None
