"""OilPriceAPI / API Ninjas / Riksbank adapters: parsing, routing, key handling."""
from __future__ import annotations

import json

import httpx
import pytest

from app.services.macro_registry.adapters.base import build_raw_response
from app.services.macro_registry.adapters.central_bank import CentralBankAdapter
from app.services.macro_registry.adapters.energy import EnergyAdapter
from app.services.macro_registry.seed import INSTRUMENT_TO_LEGACY_CODE, MACRO_SOURCE_SEED
from app.services.macro_registry.spot_clients import (
    SourceKeyMissing,
    fetch_oilpriceapi,
    parse_api_ninjas_commodity,
    parse_oilpriceapi,
    parse_riksbank_observations,
)
from app.services.macro_registry.types import MacroSourceConfig


def _config(source_id: str, category: str, symbol: str, endpoint: str) -> MacroSourceConfig:
    return MacroSourceConfig(
        source_id=source_id,
        category=category,
        symbol=symbol,
        endpoint=endpoint,
        refresh_interval="0 8 * * *",
        priority=5,
        is_free=False,
        fallback_source=None,
        transformer="transform_fred_level",
    )


def test_oilpriceapi_past_month_keeps_last_price_per_day():
    payload = {
        "status": "success",
        "data": {
            "prices": [
                {"price": 81.1, "created_at": "2026-10-19T08:00:00Z", "code": "BRENT_CRUDE_USD"},
                {"price": 81.9, "created_at": "2026-10-19T16:00:00Z", "code": "BRENT_CRUDE_USD"},
                {"price": 80.4, "created_at": "2026-10-18T16:00:00.000Z", "code": "BRENT_CRUDE_USD"},
            ]
        },
    }
    rows = parse_oilpriceapi(json.dumps(payload))
    assert [r["value"] for r in rows] == [80.4, 81.9]


def test_oilpriceapi_latest_shape():
    rows = parse_oilpriceapi({"status": "success", "data": {"price": 77.5, "created_at": "2026-10-20T10:00:00Z"}})
    assert rows[0]["value"] == 77.5


def test_energy_adapter_normalizes_oilpriceapi_brent():
    cfg = _config("oilpriceapi_brent", "energy", "BRENT_OIL", "adapter:oilpriceapi:BRENT_CRUDE_USD")
    raw = build_raw_response(cfg, json.dumps({"data": {"prices": [{"price": 82.0, "created_at": "2026-10-20T10:00:00Z"}]}}))
    rows = EnergyAdapter(cfg).normalize(raw)
    assert rows[-1].value == 82.0
    assert rows[-1].unit == "USD/barrel"
    assert rows[-1].instrument == "BRENT_OIL"


def test_api_ninjas_commodity_gold():
    cfg = _config("apininjas_gold", "commodity", "GOLD", "adapter:apininjas:gold")
    payload = json.dumps({"exchange": "COMEX", "name": "Gold Futures", "price": 2412.3, "updated": 1792500000})
    rows = EnergyAdapter(cfg).normalize(build_raw_response(cfg, payload))
    assert rows[0].value == pytest.approx(2412.3)
    assert rows[0].unit == "USD/oz"
    assert parse_api_ninjas_commodity({"error": "x"}) == []


def test_riksbank_policy_rate_normalize_sorted():
    payload = json.dumps([{"date": "2026-10-17", "value": 1.75}, {"date": "2026-10-16", "value": 1.75}])
    assert [r["published_at"].day for r in parse_riksbank_observations(payload)] == [16, 17]
    cfg = _config("riksbank_policy_rate", "rate", "SE_POLICY_RATE", "adapter:riksbank:SECBREPOEFF")
    rows = CentralBankAdapter(cfg).normalize(build_raw_response(cfg, payload))
    assert rows[-1].currency == "SEK" and rows[-1].unit == "%"


@pytest.mark.asyncio
async def test_missing_key_raises_so_fallback_is_used(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "OILPRICEAPI_API_KEY", "")
    async with httpx.AsyncClient() as client:
        with pytest.raises(SourceKeyMissing):
            await fetch_oilpriceapi(client, "BRENT_CRUDE_USD")


@pytest.mark.asyncio
async def test_oilpriceapi_sends_token_header(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "OILPRICEAPI_API_KEY", "k123")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["code"] = request.url.params.get("by_code")
        return httpx.Response(200, json={"data": {"prices": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await fetch_oilpriceapi(client, "WTI_USD")
    assert seen == {"auth": "Token k123", "code": "WTI_USD"}


def test_seed_has_new_sources_with_fallbacks():
    by_id = {r["source_id"]: r for r in MACRO_SOURCE_SEED}
    assert by_id["oilpriceapi_brent"]["fallback_source"] == "fred_brent"
    assert by_id["riksbank_policy_rate"]["endpoint"] == "adapter:riksbank:SECBREPOEFF"
    assert {"apininjas_gold", "apininjas_copper"} <= set(by_id)
    for row in MACRO_SOURCE_SEED:
        fb = row["fallback_source"]
        assert fb is None or fb in by_id, (row["source_id"], fb)
    assert INSTRUMENT_TO_LEGACY_CODE["SE_POLICY_RATE"] == "rate_cb_se"
