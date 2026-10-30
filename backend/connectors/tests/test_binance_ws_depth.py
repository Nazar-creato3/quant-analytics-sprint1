"""Unit tests for Binance WS depth stream helpers."""
from __future__ import annotations

from connectors.binance_ws import _depth_payload, _symbol_from_stream, build_stream_url


def test_build_stream_url_includes_depth():
    url = build_stream_url(["btcusdt"])
    assert "btcusdt@trade" in url
    assert "btcusdt@depth20@100ms" in url


def test_symbol_from_stream():
    assert _symbol_from_stream("btcusdt@depth20@100ms") == "BTCUSDT"
    assert _symbol_from_stream("") is None


def test_depth_payload_normalizes_levels():
    payload = _depth_payload(
        "BTCUSDT",
        {
            "lastUpdateId": 99,
            "bids": [["100", "1"]],
            "asks": [["101", "2"]],
            "E": 1_700_000_000_000,
        },
    )
    assert payload["symbol"] == "BTCUSDT"
    assert payload["bids"] == [["100", "1"]]
    assert payload["asks"] == [["101", "2"]]
