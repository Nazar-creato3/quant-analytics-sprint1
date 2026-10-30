"""MOEX currency instruments + T-Bank order routing tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.enums import AssetCategory, InstrumentSource
from app.services.broker.tinkoff_orders import TinkoffExecutor, is_tinkoff_routable_ticker
from app.services.execution.adapter import OrderRequest, _RoutingExecutor, PaperExecutor
from app.services.execution.guard import ManualOrderExecutionContext
from app.services.instrument.category import detect_ticker_category, watchlist_filter_key
from app.services.market_data.moex_currency import (
    is_moex_currency_ticker,
    list_moex_currency_instruments,
    normalize_moex_currency_symbol,
)
from app.services.orders.symbol_rules import get_symbol_trading_rules, round_price


class TestMoexCurrencyDetection:
    def test_usd_rub_alias(self):
        assert normalize_moex_currency_symbol("USD/RUB") == "USD000UTSTOM"
        assert is_moex_currency_ticker("USDRUB")

    def test_eur_rub_alias(self):
        assert normalize_moex_currency_symbol("EURRUB") == "EUR000UTSTOM"
        assert is_moex_currency_ticker("EUR/RUB")

    def test_cny_rub(self):
        assert normalize_moex_currency_symbol("CNY/RUB") == "CNY000UTSTOM"

    def test_universe_includes_primary_pairs(self):
        symbols = {row["symbol"] for row in list_moex_currency_instruments()}
        assert "USD000UTSTOM" in symbols
        assert "EUR000UTSTOM" in symbols
        assert "CNY000UTSTOM" in symbols

    def test_category_fx_and_watchlist_tab(self):
        info = detect_ticker_category("USD000UTSTOM")
        assert info.category == AssetCategory.FX
        assert info.source == InstrumentSource.TINKOFF
        assert watchlist_filter_key(info) == "currencies"

    def test_tinkoff_routable(self):
        assert is_tinkoff_routable_ticker("USD000UTSTOM")
        assert is_tinkoff_routable_ticker("SBER")
        assert not is_tinkoff_routable_ticker("AAPL")


class TestMoexCurrencySymbolRules:
    @pytest.mark.asyncio
    async def test_usd_rub_tick_size(self):
        with patch(
            "app.services.orders.symbol_rules.fetch_moex_currency_rules",
            new_callable=AsyncMock,
            return_value={"tick_size": 0.0025, "lot_size": 1000.0, "min_qty": 1000.0},
        ):
            rules = await get_symbol_trading_rules("USD/RUB")
        assert rules.venue == "moex_fx"
        assert rules.tick_size == 0.0025
        assert rules.lot_size == 1000.0
        assert rules.price_decimals == 4
        assert round_price(95.1234, rules) == pytest.approx(95.1225)

    @pytest.mark.asyncio
    async def test_eur_rub_rules(self):
        with patch(
            "app.services.orders.symbol_rules.fetch_moex_currency_rules",
            new_callable=AsyncMock,
            return_value={"tick_size": 0.0025, "lot_size": 1000.0, "min_qty": 1000.0},
        ):
            rules = await get_symbol_trading_rules("EUR000UTSTOM")
        assert rules.ticker == "EUR000UTSTOM"
        assert rules.price_decimals == 4


class TestTinkoffCurrencyOrders:
    @staticmethod
    def _client(captured: list, *, status: str, ticker: str, figi: str):
        import json as _json

        import httpx

        from app.services.broker import tbank_api
        from app.services.broker.tbank_api import TBankClient

        tbank_api._INSTRUMENT_CACHE.clear()
        inst = {
            "figi": figi, "uid": f"uid-{ticker}", "ticker": ticker, "classCode": "CETS", "lot": 1000,
            "currency": "rub", "minPriceIncrement": {"units": "0", "nano": 2500000},
            "apiTradeAvailableFlag": True, "buyAvailableFlag": True, "sellAvailableFlag": True,
        }

        def handler(request: httpx.Request) -> httpx.Response:
            method = request.url.path.rsplit(".", 1)[-1]
            body = _json.loads(request.content or b"{}")
            if method == "UsersService/GetAccounts":
                return httpx.Response(200, json={"accounts": [{"id": "acc-1", "type": "ACCOUNT_TYPE_TINKOFF",
                    "status": "ACCOUNT_STATUS_OPEN", "accessLevel": "ACCOUNT_ACCESS_LEVEL_FULL_ACCESS"}]})
            if method == "InstrumentsService/GetInstrumentBy":
                assert body["classCode"] == "CETS" and body["id"] == ticker
                return httpx.Response(200, json={"instrument": inst})
            if method == "MarketDataService/GetLastPrices":
                return httpx.Response(200, json={"lastPrices": [{"price": {"units": "95", "nano": 500000000}}]})
            if method == "OrdersService/PostOrder":
                captured.append(body)
                return httpx.Response(200, json={"orderId": f"ord-{ticker}", "executionReportStatus": status,
                    "lotsExecuted": "1" if status.endswith("FILL") else "0",
                    "executedOrderPrice": {"units": "95", "nano": 500000000}})
            return httpx.Response(404, json={"code": 5})

        return TBankClient("test-token", sandbox=True, transport=httpx.MockTransport(handler))

    @pytest.mark.asyncio
    async def test_usd_rub_market_order_submitted(self):
        captured: list = []
        client = self._client(captured, status="EXECUTION_REPORT_STATUS_FILL", ticker="USD000UTSTOM", figi="BBG0013HGFT4")
        executor = TinkoffExecutor(token="test-token", sandbox=True, client=client)
        req = OrderRequest(
            ticker="USD/RUB",
            side="buy",
            qty=1000.0,
            order_type="market",
            manual_order_context=ManualOrderExecutionContext(manual_order_id="mo-usd"),
        )
        result = await executor.submit_order(req)
        assert result.status == "filled"
        assert result.broker_order_id == "ord-USD000UTSTOM"
        assert result.filled_price == pytest.approx(95.5)
        assert result.filled_qty == 1000.0
        assert captured[0]["direction"] == "ORDER_DIRECTION_BUY"
        assert captured[0]["quantity"] == "1"

    @pytest.mark.asyncio
    async def test_eur_rub_limit_order_submitted(self):
        captured: list = []
        client = self._client(captured, status="EXECUTION_REPORT_STATUS_NEW", ticker="EUR000UTSTOM", figi="BBG0013HJJ31")
        executor = TinkoffExecutor(token="test-token", sandbox=True, client=client)
        req = OrderRequest(
            ticker="EUR000UTSTOM",
            side="sell",
            qty=1000.0,
            order_type="limit",
            limit_price=102.5025,
            manual_order_context=ManualOrderExecutionContext(manual_order_id="mo-eur"),
        )
        result = await executor.submit_order(req)
        assert result.status == "submitted"
        assert captured[0]["orderType"] == "ORDER_TYPE_LIMIT"
        assert captured[0]["price"]["units"] == "102"
        assert result.broker_order_id == "ord-EUR000UTSTOM"

    @pytest.mark.asyncio
    async def test_routing_executor_sends_moex_fx_to_tinkoff(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "LIVE_TRADING_ENABLED", True)
        monkeypatch.setattr(settings, "LIVE_TRADING_CONFIRMATION", "I_UNDERSTAND_THE_RISKS")
        monkeypatch.setattr(settings, "PAPER_TRADING_ENABLED", True)

        tinkoff = AsyncMock()
        from datetime import datetime, timezone

        from app.services.execution.adapter import OrderResult

        tinkoff.submit_order = AsyncMock(
            return_value=OrderResult(
                broker_order_id="tb-1",
                status="submitted",
                filled_price=None,
                filled_qty=None,
                submitted_at=datetime.now(timezone.utc),
            )
        )
        paper = PaperExecutor()
        router = _RoutingExecutor(tinkoff=tinkoff, paper=paper, alpaca=AsyncMock())
        req = OrderRequest(
            ticker="USD000UTSTOM",
            side="buy",
            qty=1000,
            order_type="limit",
            limit_price=95.0,
            manual_order_context=ManualOrderExecutionContext(manual_order_id="r1"),
        )
        await router.submit_order(req)
        tinkoff.submit_order.assert_awaited_once()


class TestDirectDealsCurrencySymbols:
    @patch(
        "app.api.v1.endpoints.direct_deals.get_effective_watchlist",
        new_callable=AsyncMock,
        return_value=[],
    )
    def test_symbols_include_moex_fx(self, _mock_watchlist):
        from app.api.v1.endpoints.direct_deals import router
        from app.core.deps import get_current_user_email, get_db
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        async def fake_user():
            return "user@test.com"

        async def fake_db():
            db = AsyncMock()
            db.execute.return_value = MagicMock(
                scalars=MagicMock(return_value=MagicMock(all=lambda: []))
            )
            yield db

        app.dependency_overrides[get_current_user_email] = fake_user
        app.dependency_overrides[get_db] = fake_db

        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/v1/direct-deals/symbols?q=USD")
            assert resp.status_code == 200
            symbols = {row["symbol"]: row for row in resp.json()}
            assert "USD000UTSTOM" in symbols
            assert symbols["USD000UTSTOM"]["asset_class"] == "fx"
            assert symbols["USD000UTSTOM"]["exchange"] == "MOEX"

            resp_eur = c.get("/api/v1/direct-deals/symbols?q=EUR000")
            body = {row["symbol"]: row for row in resp_eur.json()}
            assert "EUR000UTSTOM" in body
            assert body["EUR000UTSTOM"]["asset_class"] == "fx"
