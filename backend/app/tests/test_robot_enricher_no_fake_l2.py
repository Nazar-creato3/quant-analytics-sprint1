"""GA16-317: enrich_ticker must not invent order book or tape rows."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.robot import enricher


@pytest.mark.asyncio
async def test_ga16_317_enrich_does_not_write_fake_book_or_tape(monkeypatch):
    bars = [
        SimpleNamespace(close=100.0 + i)
        for i in range(30)
    ]
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(reversed(bars))
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)

    store_ob = AsyncMock()
    store_tp = AsyncMock()
    monkeypatch.setattr(enricher, "store_orderbook", store_ob)
    monkeypatch.setattr(enricher, "store_tape", store_tp)

    out = await enricher.enrich_ticker(db, ticker="SBER")
    assert out["ticker"] == "SBER"
    assert out["bars"] == 30
    store_ob.assert_not_awaited()
    store_tp.assert_not_awaited()
