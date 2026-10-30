"""Tests for order book exchange session metadata."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.schemas.orders import OrderBookLevel, OrderBookSnapshot
from app.services.orders.order_book_session import (
    build_session_message_ru,
    enrich_order_book_session,
    resolve_exchange_for_ticker,
    session_status_for_ticker,
)


def test_resolve_exchange_crypto():
    ex_id, name_ru = resolve_exchange_for_ticker("BTCUSDT")
    assert ex_id == "BINANCE"
    assert name_ru == "Binance"


def test_resolve_exchange_moex():
    ex_id, _ = resolve_exchange_for_ticker("SBER")
    assert ex_id == "MOEX"


def test_resolve_exchange_nasdaq():
    ex_id, _ = resolve_exchange_for_ticker("MSFT")
    assert ex_id == "NASDAQ"


def test_resolve_exchange_qqq_nasdaq():
    ex_id, _ = resolve_exchange_for_ticker("QQQ")
    assert ex_id == "NASDAQ"


def test_resolve_exchange_nyse_default():
    ex_id, _ = resolve_exchange_for_ticker("JPM")
    assert ex_id == "NYSE"


def test_session_message_ru_closed():
    msg = build_session_message_ru("MOEX", "closed")
    assert msg == "MOEX · торговая сессия закрыта"


def test_session_message_ru_crypto():
    msg = build_session_message_ru("BINANCE", "open")
    assert "24/7" in msg


@patch("app.services.orders.order_book_session.session_status_for_exchange")
def test_session_status_crypto_always_open(mock_status):
    assert session_status_for_ticker("BTCUSDT") == "open"
    mock_status.assert_not_called()


@patch("app.services.orders.order_book_session.session_status_for_exchange", return_value="closed")
def test_session_status_moex_weekend(_mock_status):
    assert session_status_for_ticker("SBER") == "closed"


def test_enrich_order_book_session_fields():
    snap = OrderBookSnapshot(
        ticker="SBER",
        bids=[],
        asks=[],
        depth_available=False,
        session_label="NBBO без глубины",
    )
    enriched = enrich_order_book_session(snap, "SBER")
    assert enriched.exchange_id == "MOEX"
    assert enriched.exchange_name_ru == "MOEX"
    assert enriched.session_status in {"open", "closed", "pre", "post"}
    assert enriched.session_message_ru is not None
    assert enriched.session_label == "NBBO без глубины"


@patch("app.services.orders.order_book_session.session_status_for_exchange", return_value="closed")
def test_enrich_closed_sets_depth_reason(_mock_status):
    snap = OrderBookSnapshot(
        ticker="NVDA",
        bids=[OrderBookLevel(price=100.0, size=0.0)],
        asks=[OrderBookLevel(price=101.0, size=0.0)],
        depth_available=False,
        source="yfinance_nbbo_thin",
        session_label="глубина недоступна · Yahoo NBBO",
        depth_unavailable_reason="Alpaca: таймаут · Yahoo NBBO без объёмов",
    )
    enriched = enrich_order_book_session(snap, "NVDA")
    assert enriched.session_status == "closed"
    assert enriched.session_label is not None
    assert "сессия закрыта" in (enriched.session_label or "")
    assert "Alpaca" in (enriched.depth_unavailable_reason or "")
    assert "закрыта" in (enriched.depth_unavailable_reason or "")


@pytest.mark.asyncio
@patch("app.services.orders.order_book_session.session_status_for_exchange", return_value="closed")
async def test_fetch_order_book_includes_session_meta(_mock_status):
    from app.services.orders.order_book import fetch_order_book

    sample = OrderBookSnapshot(
        ticker="MSFT",
        bids=[OrderBookLevel(price=400.0, size=0.0)],
        asks=[OrderBookLevel(price=400.1, size=0.0)],
        mid_price=400.05,
        spread_bps=2.5,
        source="yfinance_nbbo_thin",
        depth_available=False,
        session_label="глубина недоступна · NBBO",
        depth_unavailable_reason="Alpaca: таймаут · Yahoo NBBO",
        as_of=datetime.now(timezone.utc),
    )
    with patch(
        "app.services.orders.order_book._fetch_alpaca_depth",
        return_value=sample,
    ):
        book = await fetch_order_book("MSFT", levels=5)

    assert book.exchange_id == "NASDAQ"
    assert book.session_status == "closed"
    assert "закрыта" in (book.session_message_ru or "")
    assert book.session_label is not None
    assert book.depth_unavailable_reason is not None
