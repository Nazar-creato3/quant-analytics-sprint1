"""Tests for MOEX ISS client (platform credentials, board resolution)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


def test_moex_platform_configured_with_passport():
    from app.services.trading_keys.platform_keys import moex_platform_configured

    with patch.dict(
        "os.environ",
        {"MOEX_USERNAME": "user", "MOEX_PASSWORD": "pass", "MOEX_API_TOKEN": ""},
        clear=False,
    ):
        assert moex_platform_configured() is True


def test_pick_board_prefers_tqbr():
    from app.services.market_data.moex_iss_client import _pick_board_from_marketdata

    payload = {
        "marketdata": {
            "columns": ["SECID", "BOARDID", "BID", "OFFER", "LAST"],
            "data": [
                ["EQMX", "TQTF", 0, 0, 0],
                ["EQMX", "TQBR", 124.75, 124.85, 124.8],
            ],
        }
    }
    assert _pick_board_from_marketdata(payload) == "TQBR"


@pytest.mark.asyncio
async def test_fetch_moex_share_orderbook_json_uses_authenticated_client():
    from app.services.market_data import moex_iss_client

    iss_payload = {
        "orderbook": {
            "columns": ["BUYSELL", "PRICE", "QUANTITY"],
            "data": [["B", 100.0, 10]],
        }
    }

    with patch(
        "app.services.market_data.moex_iss_client.fetch_moex_iss_json",
        new_callable=AsyncMock,
        side_effect=[{"marketdata": {"columns": ["BOARDID", "BID"], "data": [["TQBR", 1]]}}, iss_payload],
    ):
        payload = await moex_iss_client.fetch_moex_share_orderbook_json("SBER")

    assert payload == iss_payload


def test_normalize_iss_tables_from_aiomoex_list():
    from app.services.market_data.moex_iss_client import normalize_iss_tables

    payload = normalize_iss_tables(
        {"orderbook": [{"BUYSELL": "B", "PRICE": 100.0, "QUANTITY": 10}]}
    )
    assert payload is not None
    assert payload["orderbook"]["columns"] == ["BUYSELL", "PRICE", "QUANTITY"]
    assert payload["orderbook"]["data"] == [["B", 100.0, 10]]


def test_tinkoff_rest_base_defaults_to_live(monkeypatch):
    from app.services.integration.historical_data import tinkoff_rest_base, tinkoff_rpc

    monkeypatch.delenv("TINKOFF_SANDBOX", raising=False)
    monkeypatch.delenv("TINKOFF_BASE_URL", raising=False)
    assert tinkoff_rest_base() == "invest-public-api.tbank.ru"
    assert "invest-public-api.tbank.ru" in tinkoff_rpc("MarketDataService/GetOrderBook")


def test_tinkoff_sandbox_only_when_explicit(monkeypatch):
    from app.services.integration.historical_data import tinkoff_rest_base

    monkeypatch.setenv("TINKOFF_SANDBOX", "true")
    monkeypatch.delenv("TINKOFF_BASE_URL", raising=False)
    assert tinkoff_rest_base() == "sandbox-invest-public-api.tbank.ru"
    from app.services.orders.order_book import _parse_moex_iss_orderbook_payload

    snap = _parse_moex_iss_orderbook_payload(
        {
            "orderbook": {
                "columns": ["BUYSELL", "PRICE", "QUANTITY"],
                "data": [["B", 128.5, 500], ["S", 128.55, 700]],
            }
        },
        bare="SBER",
        levels=5,
        source="moex_iss_orderbook",
    )
    assert snap is not None
    assert snap.source == "moex_iss_orderbook"
    assert snap.bids[0].size == 500.0
    assert snap.asks[0].price == 128.55
