"""Bybit tokenized equity symbol mapping vs live exchange instruments."""
from __future__ import annotations

import httpx
import pytest

from app.services.execution.symbol_mapping import (
    _BYBIT_TOKENIZED,
    execution_ticker_for,
    list_tokenized_equity_symbols,
    resolve_symbol_route,
)

_BYBIT_INSTRUMENTS_URL = "https://api.bybit.com/v5/market/instruments-info"


@pytest.mark.parametrize("ui_symbol", list_tokenized_equity_symbols())
def test_bybit_execution_ticker_uses_xusdt_format(ui_symbol: str) -> None:
    ticker = execution_ticker_for(ui_symbol, provider_type="bybit")
    assert ticker.endswith("USDT"), f"{ui_symbol} -> {ticker} must end with USDT"
    assert ticker.endswith("XUSDT"), f"{ui_symbol} -> {ticker} must use Bybit tokenized XUSDT suffix"
    route = resolve_symbol_route(ui_symbol, provider_type="bybit")
    assert route.execution_provider_ticker == ticker
    assert route.execution_venue == "tokenized_equity"


def test_unknown_us_equity_gets_dynamic_xusdt_candidate() -> None:
    ticker = execution_ticker_for("HOOD", provider_type="bybit")
    assert ticker == "HOODXUSDT"
    assert "HOOD" not in _BYBIT_TOKENIZED


@pytest.mark.integration
def test_bybit_live_tokenized_symbols_use_xusdt_suffix() -> None:
    resp = httpx.get(
        _BYBIT_INSTRUMENTS_URL,
        params={"category": "spot", "limit": "1000"},
        timeout=30.0,
    )
    resp.raise_for_status()
    payload = resp.json()
    assert int(payload.get("retCode", -1)) == 0
    tokenized = [
        row["symbol"]
        for row in (payload.get("result") or {}).get("list") or []
        if str(row.get("symbol", "")).endswith("XUSDT")
    ]
    assert tokenized, "expected at least one *XUSDT instrument on Bybit spot"
    for sym in tokenized[:5]:
        assert sym.endswith("XUSDT")
