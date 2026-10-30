"""Tests for Binance spot helpers and paper auto-execute."""
from __future__ import annotations

import pytest

from app.services.market_data.binance_spot import (
    is_crypto_ticker,
    ticker_to_binance_symbol,
)
from app.services.execution.auto_execute import paper_auto_execute_enabled


def test_ticker_to_binance_symbol_btc():
    assert ticker_to_binance_symbol("BTC-USD") == "BTCUSDT"
    assert ticker_to_binance_symbol("btc-usd") == "BTCUSDT"


def test_ticker_to_binance_symbol_equity_none():
    assert ticker_to_binance_symbol("AAPL") is None
    assert ticker_to_binance_symbol("SPY") is None


def test_is_crypto_ticker():
    assert is_crypto_ticker("BTC-USD") is True
    assert is_crypto_ticker("AAPL") is False


def test_paper_auto_execute_enabled_default(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "PAPER_TRADING_ENABLED", True)
    monkeypatch.setattr(settings, "PAPER_AUTO_EXECUTE", True)
    monkeypatch.setattr(settings, "LIVE_TRADING_ENABLED", False)
    monkeypatch.setattr(settings, "LIVE_TRADING_CONFIRMATION", "")
    assert paper_auto_execute_enabled() is True

    monkeypatch.setattr(settings, "PAPER_AUTO_EXECUTE", False)
    assert paper_auto_execute_enabled() is False
