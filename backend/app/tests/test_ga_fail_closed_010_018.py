"""GA-010…GA-018: paper fill and venue parsers refuse missing price/qty."""
from __future__ import annotations

import asyncio
import inspect

import pytest

from app.services.execution.adapter import OrderRequest, PaperExecutor
from app.services.execution.guard import ManualOrderExecutionContext
from app.services.execution.providers.bybit_tokenized import BybitTokenizedEquityProvider
from app.services.execution.providers.mexc_tokenized import MexcTokenizedEquityProvider
from app.services.execution.providers.mock import MockExecutionProvider
from app.services.execution.providers.types import Position


@pytest.mark.asyncio
async def test_ga010_paper_fill_refuses_missing_quote_price(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_price(ticker: str):  # noqa: ARG001
        return {"bid": None, "ask": None, "price": None}

    monkeypatch.setattr(
        "app.services.market_data.client.get_latest_quote_resolved",
        no_price,
    )
    result = await PaperExecutor().submit_order(
        OrderRequest(
            ticker="SBER",
            side="buy",
            qty=1.0,
            order_type="market",
            limit_price=0.0,
            manual_order_context=ManualOrderExecutionContext(manual_order_id="mo-ga010"),
        )
    )
    assert result.status == "rejected"
    assert result.error == "нет данных"
    assert result.filled_price is None


def test_ga011_maneuver_fill_source_has_no_invented_qty() -> None:
    from app.services.execution import adapter as adapter_mod

    src = inspect.getsource(adapter_mod._execute_maneuver_in_session)
    assert "max(position_usd / 100.0" not in src
    assert "coerce_finite_float(qty, 0.0001)" not in src
    assert "except Exception:\n        pass" not in src
    assert "Refuse paper fill without reference price" in src


@pytest.mark.asyncio
async def test_ga012_013_bybit_history_skips_incomplete_rows() -> None:
    provider = BybitTokenizedEquityProvider(api_key="test", api_secret="test")

    async def fake_request(method, path, params=None):  # noqa: ANN001, ARG001
        return {
            "list": [
                {"symbol": "SBERX", "qty": None, "createdTime": "1", "orderStatus": "New"},
                {
                    "symbol": "SBERX",
                    "qty": "10",
                    "createdTime": "1700000000000",
                    "orderStatus": "Filled",
                    "cumExecQty": "bad",
                    "side": "Buy",
                    "orderType": "Market",
                    "orderId": "1",
                },
                {
                    "symbol": "SBERX",
                    "qty": "2",
                    "createdTime": "1700000001000",
                    "orderStatus": "New",
                    "cumExecQty": "0",
                    "side": "Buy",
                    "orderType": "Limit",
                    "orderId": "2",
                    "price": "100",
                },
            ]
        }

    provider._request = fake_request  # type: ignore[method-assign]
    orders = await provider.get_order_history(symbol="SBER", limit=10)
    assert len(orders) == 1
    assert orders[0].qty == 2.0
    assert orders[0].filled_qty == 0.0


@pytest.mark.asyncio
async def test_ga014_bybit_tick_skips_missing_last_price(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = BybitTokenizedEquityProvider(api_key="test", api_secret="test")
    calls = {"n": 0}

    async def fake_request(method, path, params=None):  # noqa: ANN001, ARG001
        calls["n"] += 1
        return {"list": [{"lastPrice": None}]}

    provider._request = fake_request  # type: ignore[method-assign]

    async def stop_sleep(_seconds: float) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", stop_sleep)
    ticks: list[object] = []
    with pytest.raises(asyncio.CancelledError):
        async for tick in provider.stream_prices(["SBER"]):
            ticks.append(tick)
    assert ticks == []
    assert calls["n"] >= 1


@pytest.mark.asyncio
async def test_ga015_mexc_place_order_refuses_bad_executed_qty() -> None:
    provider = MexcTokenizedEquityProvider(api_key="test", api_secret="test")

    async def fake_request(method, path, params=None):  # noqa: ANN001, ARG001
        return {"orderId": "9", "executedQty": "not-a-number", "price": "100"}

    provider._request = fake_request  # type: ignore[method-assign]
    result = await provider.place_order("SBER", "buy", 1.0, order_type="market")
    assert result.ok is False
    assert result.error == "нет данных"


@pytest.mark.asyncio
async def test_ga016_017_mexc_history_skips_incomplete_rows() -> None:
    provider = MexcTokenizedEquityProvider(api_key="test", api_secret="test")

    async def fake_request(method, path, params=None):  # noqa: ANN001, ARG001
        return [
            {"symbol": "SBERUSDT", "origQty": None, "time": 1, "status": "NEW"},
            {
                "symbol": "SBERUSDT",
                "origQty": "3",
                "time": 1700000000000,
                "status": "FILLED",
                "executedQty": "x",
                "side": "BUY",
                "type": "MARKET",
                "orderId": "1",
            },
            {
                "symbol": "SBERUSDT",
                "origQty": "4",
                "time": 1700000001000,
                "status": "NEW",
                "executedQty": "0",
                "side": "BUY",
                "type": "LIMIT",
                "orderId": "2",
                "price": "50",
            },
        ]

    provider._request = fake_request  # type: ignore[method-assign]
    orders = await provider.get_order_history(symbol="SBER", limit=10)
    assert len(orders) == 1
    assert orders[0].qty == 4.0
    assert orders[0].filled_qty == 0.0


@pytest.mark.asyncio
async def test_ga019_020_mock_refuses_missing_prices() -> None:
    provider = MockExecutionProvider()
    provider._positions["ORPHAN"] = Position(
        symbol="ORPHAN",
        execution_symbol="ORPHAN",
        qty=2.0,
        avg_entry_price=None,
        mark_price=None,
        unrealized_pnl_usd=None,
    )
    bal = await provider.get_account_balance()
    assert bal.balances[0].locked == 0.0

    provider._positions["SBER"] = Position(
        symbol="SBER",
        execution_symbol="SBER",
        qty=1.0,
        avg_entry_price=None,
        mark_price=100.0,
        unrealized_pnl_usd=None,
    )
    result = await provider.place_order("SBER", "buy", 1.0, order_type="limit", price=110.0)
    assert result.ok is False
    assert result.error == "нет данных"


@pytest.mark.asyncio
async def test_ga018_mexc_tick_skips_missing_price(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = MexcTokenizedEquityProvider(api_key="test", api_secret="test")
    calls = {"n": 0}

    async def fake_request(method, path, params=None):  # noqa: ANN001, ARG001
        calls["n"] += 1
        return {"price": None}

    provider._request = fake_request  # type: ignore[method-assign]

    async def stop_sleep(_seconds: float) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", stop_sleep)
    ticks: list[object] = []
    with pytest.raises(asyncio.CancelledError):
        async for tick in provider.stream_prices(["SBER"]):
            ticks.append(tick)
    assert ticks == []
    assert calls["n"] >= 1
