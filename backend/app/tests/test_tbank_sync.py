"""T-Bank client + book sync against a fake broker (no network)."""
from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest

from app.services.broker import tbank_api
from app.services.broker.tbank_api import TBankApiError, TBankClient, money, to_quotation
from app.services.broker.tbank_sync import book_account_id, map_operation, sync_tbank_token
from app.services.portfolio_book.store import get_book


def _m(v: str, ccy: str = "rub") -> dict:
    d = Decimal(v)
    q = to_quotation(d)
    return {"currency": ccy, **q}


ACCOUNT = {
    "id": "2000111",
    "type": "ACCOUNT_TYPE_TINKOFF",
    "name": "Брокерский счёт",
    "status": "ACCOUNT_STATUS_OPEN",
    "openedDate": "2023-01-10T00:00:00Z",
    "accessLevel": "ACCOUNT_ACCESS_LEVEL_READ_ONLY",
}

OPERATIONS = [
    {"id": "op1", "type": "OPERATION_TYPE_INPUT", "date": "2024-01-05T10:00:00Z", "payment": _m("100000")},
    {
        "id": "op2",
        "type": "OPERATION_TYPE_BUY",
        "date": "2024-01-06T10:00:00Z",
        "ticker": "SBER",
        "classCode": "TQBR",
        "payment": _m("-27000"),
        "quantity": "100",
        "quantityRest": "0",
    },
    {"id": "op3", "type": "OPERATION_TYPE_BROKER_FEE", "date": "2024-01-06T10:00:00Z", "ticker": "SBER", "payment": _m("-8.1")},
    {
        "id": "op4",
        "type": "OPERATION_TYPE_SELL",
        "date": "2024-03-01T10:00:00Z",
        "ticker": "SBER",
        "payment": _m("9000"),
        "quantity": "30",
    },
    {"id": "op5", "type": "OPERATION_TYPE_DIVIDEND", "date": "2024-07-20T10:00:00Z", "ticker": "SBER", "payment": _m("2310")},
    {"id": "op6", "type": "OPERATION_TYPE_DIVIDEND_TAX", "date": "2024-07-20T10:00:00Z", "ticker": "SBER", "payment": _m("-300")},
]

PORTFOLIO = {
    "totalAmountPortfolio": _m("95000"),
    "totalAmountShares": _m("35000"),
    "totalAmountCurrencies": _m("60000"),
    "positions": [
        # 70 SBER from the history + 10 transferred from another broker → reconcile.
        {
            "figi": "BBG004730N88",
            "ticker": "SBER",
            "classCode": "TQBR",
            "instrumentType": "share",
            "quantity": {"units": "80", "nano": 0},
            "averagePositionPrice": _m("270"),
            "currentPrice": _m("300"),
        },
        {"figi": "RUB000UTSTOM", "ticker": "RUB000UTSTOM", "instrumentType": "currency", "quantity": {"units": "60000", "nano": 0}},
    ],
}


def _broker(calls: list[str], *, pages: int = 1):
    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit(".", 1)[-1]
        calls.append(method)
        assert request.headers["Authorization"] == "Bearer user-token"
        assert request.headers["x-app-name"]
        body = json.loads(request.content or b"{}")
        if method == "UsersService/GetAccounts":
            return httpx.Response(200, json={"accounts": [ACCOUNT]})
        if method == "OperationsService/GetOperationsByCursor":
            assert body["accountId"] == "2000111"
            assert body["state"] == "OPERATION_STATE_EXECUTED"
            if pages == 2 and not body.get("cursor"):
                return httpx.Response(200, json={"hasNext": True, "nextCursor": "c2", "items": OPERATIONS[:3]})
            items = OPERATIONS[3:] if pages == 2 else OPERATIONS
            return httpx.Response(200, json={"hasNext": False, "items": items})
        if method == "OperationsService/GetPortfolio":
            return httpx.Response(200, json=PORTFOLIO)
        return httpx.Response(404, json={"code": 5, "message": "not found"})

    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _clean_book():
    get_book().reset()
    tbank_api._INSTRUMENT_CACHE.clear()
    yield
    get_book().reset()


def test_money_and_quotation_roundtrip():
    assert money({"units": "12", "nano": 500000000}) == Decimal("12.5")
    assert money({"units": "-1", "nano": -250000000}) == Decimal("-1.25")
    assert to_quotation(Decimal("-1.25")) == {"units": "-1", "nano": -250000000}
    assert money(to_quotation("306.07")) == Decimal("306.07")


def test_map_operation_signs_follow_book_convention():
    buy = map_operation(OPERATIONS[1], ticker="SBER")
    assert buy["kind"] == "trade" and buy["qty"] == Decimal("100") and buy["amount"] == Decimal("27000")
    sell = map_operation(OPERATIONS[3], ticker="SBER")
    assert sell["qty"] == Decimal("-30") and sell["amount"] == Decimal("9000")
    assert map_operation(OPERATIONS[2], ticker="SBER")["kind"] == "fee"
    assert map_operation(OPERATIONS[5], ticker="SBER")["kind"] == "tax"
    refund = map_operation({"type": "OPERATION_TYPE_TAX_CORRECTION", "payment": _m("50")}, ticker="")
    assert refund["kind"] == "other"


@pytest.mark.asyncio
@pytest.mark.parametrize("pages", [1, 2])
async def test_sync_books_history_and_reconciles_to_broker(pages):
    calls: list[str] = []
    client = TBankClient("user-token", sandbox=False, transport=_broker(calls, pages=pages))
    out = await sync_tbank_token("user-token", user_id="u1", account_mode="live", client=client)

    assert out["ok"] and out["mode"] == "live"
    acc = out["accounts"][0]
    assert acc["added"] == len(OPERATIONS)
    assert acc["access"] == "read_only"
    assert acc["reconciled"] == [{"ticker": "SBER", "qty": "10"}]
    assert out["total_rub"] == 95000.0

    positions = get_book().positions(user_id="u1", mode="live")
    sber = [p for p in positions if p.ticker == "SBER"]
    assert len(sber) == 1 and sber[0].qty == Decimal("80")
    assert sber[0].account_id == book_account_id("live", "2000111", "u1")
    # Paper book untouched.
    assert get_book().positions(user_id="u1", mode="paper") == []
    kinds = sorted(t.kind for t in get_book().transactions(user_id="u1", mode="live"))
    assert kinds.count("dividend") == 1 and kinds.count("tax") == 1 and kinds.count("deposit") == 1


@pytest.mark.asyncio
async def test_second_sync_is_idempotent():
    calls: list[str] = []
    client = TBankClient("user-token", sandbox=False, transport=_broker(calls))
    await sync_tbank_token("user-token", user_id="u1", account_mode="live", client=client)
    n = len(get_book().transactions(user_id="u1", mode="live"))
    again = await sync_tbank_token("user-token", user_id="u1", account_mode="live", client=client)
    assert again["accounts"][0]["added"] == 0
    assert again["accounts"][0]["reconciled"] == []
    assert len(get_book().transactions(user_id="u1", mode="live")) == n


@pytest.mark.asyncio
async def test_sandbox_token_goes_to_sandbox_host_and_paper_book():
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return _broker([]).handle_request(request)  # type: ignore[attr-defined]

    client = TBankClient("user-token", sandbox=True, transport=httpx.MockTransport(handler))
    out = await sync_tbank_token("user-token", user_id="u2", account_mode="paper", client=client)
    assert out["mode"] == "paper"
    assert set(hosts) == {tbank_api.SANDBOX_HOST}
    assert get_book().positions(user_id="u2", mode="live") == []


@pytest.mark.asyncio
async def test_auth_error_is_russian_and_not_retried():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"code": 16, "message": "authentication token is missing or invalid"})

    client = TBankClient("bad", sandbox=False, transport=httpx.MockTransport(handler))
    with pytest.raises(TBankApiError) as err:
        await client.get_accounts()
    assert err.value.kind == "auth_error"
    assert err.value.message == "Токен недействителен или отозван"
    assert calls == 1


@pytest.mark.asyncio
async def test_validate_token_reports_rights(monkeypatch):
    from app.services.trading_keys import validators

    transport = _broker([])
    real_init = TBankClient.__init__

    def init(self, token, *, sandbox, timeout=20.0, transport_=None, **kw):  # noqa: ANN001
        real_init(self, token, sandbox=sandbox, timeout=timeout, transport=transport)

    monkeypatch.setattr(TBankClient, "__init__", init)
    res = await validators.validate_tinkoff_token(token="user-token", sandbox=False)
    assert res.ok and res.permission_check_status == "checked"
    assert "только чтение" in (res.account_display or "")
    assert res.withdraw_allowed is False
