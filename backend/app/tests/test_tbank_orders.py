"""T-Bank executor against a fake broker: lots, live guards, fills, brackets."""
from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest

from app.services.broker import tbank_api
from app.services.broker.tbank_api import TBankClient, to_quotation
from app.services.broker.tinkoff_orders import TinkoffExecutor, round_to_tick, shares_to_lots
from app.services.execution.adapter import OrderRequest
from app.services.execution.guard import ManualOrderExecutionContext

SBER = {
    "figi": "BBG004730N88",
    "uid": "e6123145-9665-43e0-8413-cd61b8aa9b13",
    "ticker": "SBER",
    "classCode": "TQBR",
    "lot": 10,
    "currency": "rub",
    "name": "Сбербанк",
    "instrumentType": "share",
    "minPriceIncrement": {"units": "0", "nano": 10000000},
    "apiTradeAvailableFlag": True,
    "buyAvailableFlag": True,
    "sellAvailableFlag": True,
}


def _m(v: str) -> dict:
    return {"currency": "rub", **to_quotation(Decimal(v))}


class FakeBroker:
    def __init__(self, *, equity="1000000", cash="500000", held="0", fill="EXECUTION_REPORT_STATUS_FILL", lots_done=None):
        self.equity, self.cash, self.held = equity, cash, held
        self.fill, self.lots_done = fill, lots_done
        self.orders: list[dict] = []
        self.stops: list[dict] = []
        self.hosts: set[str] = set()

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.hosts.add(request.url.host)
        method = request.url.path.rsplit(".", 1)[-1]
        body = json.loads(request.content or b"{}")
        if method == "UsersService/GetAccounts":
            return httpx.Response(200, json={"accounts": [{
                "id": "acc-1", "type": "ACCOUNT_TYPE_TINKOFF", "name": "Брокерский",
                "status": "ACCOUNT_STATUS_OPEN", "accessLevel": "ACCOUNT_ACCESS_LEVEL_FULL_ACCESS",
            }]})
        if method == "InstrumentsService/GetInstrumentBy":
            if body.get("id") in ("SBER", SBER["figi"]) and body.get("classCode", "TQBR") == "TQBR":
                return httpx.Response(200, json={"instrument": SBER})
            return httpx.Response(400, json={"code": 5, "message": "not found"})
        if method == "MarketDataService/GetLastPrices":
            return httpx.Response(200, json={"lastPrices": [{"price": {"units": "300", "nano": 0}}]})
        if method == "OperationsService/GetPortfolio":
            positions = []
            if Decimal(self.held):
                positions.append({"figi": SBER["figi"], "instrumentUid": SBER["uid"], "quantity": to_quotation(Decimal(self.held))})
            return httpx.Response(200, json={"totalAmountPortfolio": _m(self.equity), "positions": positions})
        if method == "OperationsService/GetPositions":
            return httpx.Response(200, json={"money": [_m(self.cash)], "blocked": []})
        if method == "OrdersService/PostOrder":
            self.orders.append(body)
            lots = int(body["quantity"])
            done = lots if self.lots_done is None else self.lots_done
            return httpx.Response(200, json={
                "orderId": "ex-1",
                "executionReportStatus": self.fill,
                "lotsRequested": str(lots),
                "lotsExecuted": str(done),
                "executedOrderPrice": {"currency": "rub", "units": "300", "nano": 500000000},
                "executedCommission": _m("15"),
            })
        if method == "OrdersService/GetOrderState":
            return httpx.Response(200, json={"orderId": "ex-1", "executionReportStatus": self.fill,
                                             "lotsExecuted": str(self.lots_done or 0)})
        if method == "StopOrdersService/PostStopOrder":
            self.stops.append(body)
            return httpx.Response(200, json={"stopOrderId": f"stop-{len(self.stops)}"})
        return httpx.Response(404, json={"code": 5, "message": method})


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch):
    tbank_api._INSTRUMENT_CACHE.clear()
    monkeypatch.setattr("app.services.broker.tinkoff_orders._POLL_DELAY_SEC", 0)
    yield


@pytest.fixture
def live_on(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "LIVE_TRADING_ENABLED", True)
    monkeypatch.setattr(settings, "LIVE_TRADING_CONFIRMATION", "I_UNDERSTAND_THE_RISKS")
    monkeypatch.setattr(settings, "LIVE_MAX_ORDER_PCT_OF_EQUITY", 10.0)
    monkeypatch.setattr(settings, "LIVE_MAX_ORDER_RUB", 0.0)
    monkeypatch.setattr(settings, "LIVE_MAX_ORDERS_PER_DAY", 0)
    monkeypatch.setattr(settings, "LIVE_ALLOW_SHORT", False)


def _exec(broker: FakeBroker, *, sandbox=False) -> TinkoffExecutor:
    client = TBankClient("user-token", sandbox=sandbox, transport=broker.transport())
    return TinkoffExecutor(token="user-token", sandbox=sandbox, user_id="u1", client=client)


def _req(qty: float, side="buy", **kw) -> OrderRequest:
    return OrderRequest(
        ticker="SBER", side=side, qty=qty, order_type=kw.pop("order_type", "market"),
        manual_order_context=ManualOrderExecutionContext(manual_order_id="mo-1"),
        client_order_id="maneuver-abc", **kw,
    )


def test_shares_to_lots_never_rounds_up():
    assert shares_to_lots(25, 10) == 2
    assert shares_to_lots(9.99, 10) == 0
    assert shares_to_lots(float("nan"), 10) == 0


def test_round_to_tick_never_worse_price():
    tick = Decimal("0.01")
    assert round_to_tick(Decimal("300.019"), tick, side="buy") == Decimal("300.01")
    assert round_to_tick(Decimal("300.011"), tick, side="sell") == Decimal("300.02")


@pytest.mark.asyncio
async def test_live_refused_while_trading_off():
    broker = FakeBroker()
    res = await _exec(broker).submit_order(_req(100))
    assert res.status == "rejected"
    assert "выключена" in (res.error or "")
    assert broker.orders == []


@pytest.mark.asyncio
async def test_live_order_sends_lots_not_shares(live_on):
    broker = FakeBroker()
    res = await _exec(broker).submit_order(_req(105))
    assert broker.orders[0]["quantity"] == "10"  # 105 shares → 10 lots of 10
    assert broker.orders[0]["instrumentId"] == SBER["uid"]
    assert res.status == "filled"
    assert res.filled_qty == 100.0
    assert res.filled_price == pytest.approx(300.5)
    assert res.raw["commission"] == pytest.approx(15.0)
    assert broker.hosts == {tbank_api.PROD_HOST}


@pytest.mark.asyncio
async def test_resend_uses_same_idempotency_key(live_on):
    broker = FakeBroker()
    ex = _exec(broker)
    await ex.submit_order(_req(100))
    await ex.submit_order(_req(100))
    assert broker.orders[0]["orderId"] == broker.orders[1]["orderId"]


@pytest.mark.asyncio
async def test_below_one_lot_rejected(live_on):
    broker = FakeBroker()
    res = await _exec(broker).submit_order(_req(7))
    assert res.status == "rejected" and "1 лот" in (res.error or "")
    assert broker.orders == []


@pytest.mark.asyncio
async def test_equity_cap(live_on):
    broker = FakeBroker(equity="100000", cash="100000")
    res = await _exec(broker).submit_order(_req(400))  # 40 lots × 10 × 300 = 120 000 > 10 % of 100 000
    assert res.status == "rejected" and "лимита" in (res.error or "")
    assert broker.orders == []


@pytest.mark.asyncio
async def test_cash_check(live_on):
    broker = FakeBroker(equity="1000000", cash="1000")
    res = await _exec(broker).submit_order(_req(100))
    assert res.status == "rejected" and "Недостаточно" in (res.error or "")


@pytest.mark.asyncio
async def test_no_short_sale(live_on):
    broker = FakeBroker(held="50")
    res = await _exec(broker).submit_order(_req(100, side="sell"))
    assert res.status == "rejected" and "короткие" in (res.error or "")
    ok = await _exec(FakeBroker(held="100")).submit_order(_req(100, side="sell"))
    assert ok.status == "filled"


@pytest.mark.asyncio
async def test_partial_fill_stays_open(live_on):
    broker = FakeBroker(fill="EXECUTION_REPORT_STATUS_PARTIALLYFILL", lots_done=3)
    res = await _exec(broker).submit_order(_req(100, order_type="limit", limit_price=300.0))
    assert res.status == "partially_filled"
    assert res.filled_qty == 30.0
    assert broker.orders[0]["orderType"] == "ORDER_TYPE_LIMIT"
    assert res.raw["account_id"] == "acc-1"


@pytest.mark.asyncio
async def test_brackets_after_filled_long(live_on):
    broker = FakeBroker()
    res = await _exec(broker).submit_order(_req(100, stop_loss=280.0, take_profit=330.0))
    assert res.status == "filled"
    kinds = {s["stopOrderType"] for s in broker.stops}
    assert kinds == {"STOP_ORDER_TYPE_STOP_LOSS", "STOP_ORDER_TYPE_TAKE_PROFIT"}
    assert all(s["quantity"] == "10" and s["direction"] == "STOP_ORDER_DIRECTION_SELL" for s in broker.stops)


@pytest.mark.asyncio
async def test_sandbox_skips_live_guard_and_uses_sandbox_host():
    broker = FakeBroker(equity="0", cash="0")
    res = await _exec(broker, sandbox=True).submit_order(_req(100))
    assert res.status == "filled"
    assert broker.hosts == {tbank_api.SANDBOX_HOST}


def test_apply_state_partial_then_cancelled_counts_as_fill():
    from types import SimpleNamespace

    from app.services.broker.tbank_order_refresh import apply_state

    order = SimpleNamespace(raw_response={"lot": 10, "source": "tinkoff"}, fill_quantity=None, fill_price=None,
                            status="submitted", filled_at=None, error_message=None)
    status = apply_state(order, {"executionReportStatus": "EXECUTION_REPORT_STATUS_CANCELLED", "lotsExecuted": "2",
                                 "executedOrderPrice": {"units": "301", "nano": 0}})
    assert status == "filled" and order.fill_quantity == 20.0 and order.fill_price == 301.0
