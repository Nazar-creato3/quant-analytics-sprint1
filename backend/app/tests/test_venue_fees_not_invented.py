"""GA16-264: Bybit and Binance fees must not be invented."""
from __future__ import annotations

import pytest

from app.services.robot.fees import sync_venue_fees


@pytest.mark.asyncio
async def test_exchange_fees_are_not_invented(monkeypatch: pytest.MonkeyPatch) -> None:
    written: list[str] = []

    async def upsert(_db: object, *, venue: str, **_kwargs: object) -> None:
        written.append(venue)

    class DB:
        async def commit(self) -> None:
            return None

    monkeypatch.setattr("app.services.robot.fees.upsert_venue_fee", upsert)
    monkeypatch.setattr("app.services.robot.fees._default_rates", lambda: (0.001, 0.002))

    result = await sync_venue_fees(DB())
    assert written == ["paper"]
    assert result["skipped"] == ["bybit", "binance"]
    assert result["updated"] == 1
