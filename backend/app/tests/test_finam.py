"""Finam Trade API client, sync and executor against a fake broker."""
from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest

from app.services.broker.finam_api import FinamClient, dec, money
from app.services.broker.finam_orders import FinamExecutor, whole_lots
from app.services.broker.finam_sync import map_transaction, sync_finam_secret
from app.services.execution.adapter import OrderRequest
from app.services.execution.guard import ManualOrderExecutionContext
from app.services.portfolio_book.store import get_book


def _d(v: str) -> dict:
    return {"value": v}


def _rub(units: int, nanos: int = 0) -> dict:
    return {"currency_code": "RUB", "units": str(units), "nanos": nanos}


class FakeFinam:
    def __init__(self, *, readonly=True, held="15", equity="200000", cash=150000, status="ORDER_STATUS_FILLED"):
        self.readonly, self.held, self.equity, self.cash, self.status = readonly, held, equity, cash, status
        self.orders: list[dict] = []
        self.sltp: list[dict] = []
        self.auth_calls = 0

    def transport(self):
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/sessions":
            self.auth_calls += 1
            assert json.loads(request.content)["secret"] == "fin-secret"
            return httpx.Response(200, json={"token": "jwt-1"})
        assert request.headers["Authorization"] == "jwt-1"
        if path == "/v1/sessions/details":
            return httpx.Response(200, json={"account_ids": ["A1"], "readonly": self.readonly})
        if path == "/v1/accounts/A1":
            return httpx.Response(200, json={
                "account_id": "A1", "equity": _d(self.equity), "cash": [_rub(self.cash)],
                "first_trade_date": "2025-06-01T00:00:00Z",
                "positions": [{"symbol": "SBER@MISX", "quantity": _d(self.held), "average_price": _d("280"),
                               "average_price_currency": "RUB"}] if Decimal(self.held) else [],
            })
        if path == "/v1/accounts/A1/trades":
            if request.url.params["interval.start_time"].startswith("2025-06"):
                return httpx.Response(200, json={"trades": [
                    {"trade_id": "t1", "symbol": "SBER@MISX", "price": _d("280"), "size": _d("20"),
                     "side": "SIDE_BUY", "timestamp": "2025-06-03T10:00:00Z", "currency": "RUB"},
                    {"trade_id": "t2", "symbol": "SBER@MISX", "price": _d("300"), "size": _d("10"),
                     "side": "SIDE_SELL", "timestamp": "2025-06-20T10:00:00Z", "currency": "RUB"},
                ]})
            return httpx.Response(200, json={"trades": []})
        if path == "/v1/accounts/A1/transactions":
            if request.url.params["interval.start_time"].startswith("2025-06"):
                return httpx.Response(200, json={"transactions": [
                    {"id": "x1", "transaction_category": "DEPOSIT", "timestamp": "2025-06-01T09:00:00Z", "change": _rub(100000)},
                    {"id": "x2", "transaction_category": "COMMISSION", "timestamp": "2025-06-03T10:00:00Z",
                     "symbol": "SBER@MISX", "change": _rub(-3, -500000000)},
                    {"id": "x3", "transaction_category": "OTHERS", "timestamp": "2025-06-03T10:00:00Z",
                     "symbol": "SBER@MISX", "change": _rub(-5600), "trade": {"size": _d("20"), "price": _d("280")}},
                ]})
            return httpx.Response(200, json={"transactions": []})
        if path == "/v1/assets/SBER@MISX":
            return httpx.Response(200, json={"ticker": "SBER", "lot_size": _d("10"), "min_step": 1, "decimals": 2,
                                             "quote_currency": "RUB", "name": "Сбербанк"})
        if path == "/v1/instruments/SBER@MISX/quotes/latest":
            return httpx.Response(200, json={"quote": {"last": _d("300")}})
        if path == "/v1/accounts/A1/orders" and request.method == "POST":
            body = json.loads(request.content)
            self.orders.append(body)
            return httpx.Response(200, json={"order_id": "o1", "status": self.status,
                                             "executed_quantity": body["quantity"] if self.status == "ORDER_STATUS_FILLED" else _d("0")})
        if path == "/v1/accounts/A1/orders/o1":
            return httpx.Response(200, json={"order_id": "o1", "status": self.status, "executed_quantity": _d("0")})
        if path == "/v1/accounts/A1/sltp-orders":
            self.sltp.append(json.loads(request.content))
            return httpx.Response(200, json={"order_id": "s1", "status": "ORDER_STATUS_NEW"})
        return httpx.Response(404, json={"message": path})


@pytest.fixture(autouse=True)
def _book():
    get_book().reset()
    yield
    get_book().reset()


def test_decimal_and_money():
    assert dec({"value": "12.50"}) == Decimal("12.50")
    assert money(_rub(-3, -500000000)) == (Decimal("-3.5"), "RUB")
    assert whole_lots(Decimal("25"), Decimal("10")) == Decimal("20")


def test_trade_rows_in_transactions_are_skipped():
    assert map_transaction({"id": "x", "transaction_category": "OTHERS", "change": _rub(-1), "trade": {"size": _d("1")}}) is None
    fee = map_transaction({"id": "y", "transaction_category": "COMMISSION", "change": _rub(-3, -500000000)})
    assert fee["kind"] == "fee" and fee["amount"] == Decimal("3.5")


@pytest.mark.asyncio
async def test_sync_books_and_reconciles():
    broker = FakeFinam()
    client = FinamClient("fin-secret", transport=broker.transport())
    out = await sync_finam_secret("fin-secret", user_id="u1", account_mode="live", client=client)
    acc = out["accounts"][0]
    assert out["ok"] and acc["access"] == "read_only"
    assert acc["added"] == 4  # 2 trades + deposit + commission (the trade-backed transaction is skipped)
    assert acc["reconciled"] == [{"ticker": "SBER", "qty": "5"}]  # 20 - 10 = 10 in history, broker holds 15
    pos = get_book().positions(user_id="u1", mode="live")
    assert [(p.ticker, p.qty) for p in pos] == [("SBER", Decimal("15"))]
    assert broker.auth_calls == 1  # JWT reused across calls
    again = await sync_finam_secret("fin-secret", user_id="u1", account_mode="live", client=client)
    assert again["accounts"][0]["added"] == 0 and again["accounts"][0]["reconciled"] == []


def _req(qty, side="buy", **kw):
    return OrderRequest(ticker="SBER", side=side, qty=qty, order_type="market",
                        manual_order_context=ManualOrderExecutionContext(manual_order_id="m1"),
                        client_order_id="maneuver-xyz", **kw)


@pytest.fixture
def live_on(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LIVE_TRADING_ENABLED", True)
    monkeypatch.setattr(settings, "LIVE_TRADING_CONFIRMATION", "I_UNDERSTAND_THE_RISKS")
    monkeypatch.setattr(settings, "LIVE_MAX_ORDER_PCT_OF_EQUITY", 10.0)
    monkeypatch.setattr(settings, "LIVE_MAX_ORDER_RUB", 0.0)
    monkeypatch.setattr(settings, "LIVE_MAX_ORDERS_PER_DAY", 0)
    monkeypatch.setattr(settings, "LIVE_ALLOW_SHORT", False)
    monkeypatch.setattr("app.services.broker.finam_orders._POLL_DELAY_SEC", 0)


def _exec(broker):
    return FinamExecutor(secret="fin-secret", user_id="u1", client=FinamClient("fin-secret", transport=broker.transport()))


@pytest.mark.asyncio
async def test_readonly_token_cannot_trade(live_on):
    res = await _exec(FakeFinam(readonly=True)).submit_order(_req(20))
    assert res.status == "rejected" and "только для чтения" in (res.error or "")


@pytest.mark.asyncio
async def test_live_order_whole_lots_and_brackets(live_on):
    broker = FakeFinam(readonly=False, equity="1000000", cash=500000)
    res = await _exec(broker).submit_order(_req(25, stop_loss=280.0, take_profit=330.0))
    assert broker.orders[0]["quantity"] == {"value": "20"}
    assert broker.orders[0]["symbol"] == "SBER@MISX" and broker.orders[0]["side"] == "SIDE_BUY"
    assert len(broker.orders[0]["client_order_id"]) <= 20
    assert res.status == "filled" and res.filled_qty == 20.0
    assert broker.sltp and broker.sltp[0]["sl_price"] == {"value": "280.00"}


@pytest.mark.asyncio
async def test_live_guard_equity_and_short(live_on):
    small = FakeFinam(readonly=False, equity="10000", cash=10000)
    res = await _exec(small).submit_order(_req(100))
    assert res.status == "rejected" and "лимита" in (res.error or "")
    short = await _exec(FakeFinam(readonly=False, held="5", equity="1000000")).submit_order(_req(20, side="sell"))
    assert short.status == "rejected" and "короткие" in (short.error or "")
