"""Tests for instrument resolver auto-creation."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.enums import AssetCategory, InstrumentSource
from app.services.instrument.resolver import _infer_instrument, resolve_or_create_instrument


class TestInferInstrument:
    def test_us_equity(self):
        source, category, meta = _infer_instrument("AAPL")
        assert source == InstrumentSource.FINAM
        assert category == AssetCategory.EQUITIES
        assert meta.get("sector") == "technology"

    def test_crypto_usdt(self):
        source, category, _meta = _infer_instrument("BTCUSDT")
        assert source == InstrumentSource.BINANCE
        assert category == AssetCategory.CRYPTO

    def test_crypto_dash_usd(self):
        source, category, _meta = _infer_instrument("BTC-USD")
        assert source == InstrumentSource.BINANCE
        assert category == AssetCategory.CRYPTO

    def test_moex_equity(self):
        source, category, meta = _infer_instrument("SBER")
        assert source == InstrumentSource.MOEX
        assert category == AssetCategory.EQUITIES
        assert meta.get("market") == "moex"

    def test_moex_me_suffix(self):
        source, category, _meta = _infer_instrument("GAZP.ME")
        assert source == InstrumentSource.MOEX
        assert category == AssetCategory.EQUITIES

    def test_unknown_other(self):
        _source, category, meta = _infer_instrument("ZZZZQ")
        assert category == AssetCategory.OTHER
        assert meta.get("market") == "other"


@pytest.mark.asyncio
async def test_resolve_or_create_returns_existing():
    existing = MagicMock()
    existing.symbol = "AAPL"
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing)))

    row = await resolve_or_create_instrument(db, "AAPL")
    assert row is existing
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_or_create_inserts_when_missing():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    row = await resolve_or_create_instrument(db, "MSFT")
    db.add.assert_called_once()
    assert row.symbol == "MSFT"
    assert row.source == InstrumentSource.FINAM.value
