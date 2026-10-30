"""GA16-263: a blank event effect must not be stored as 0 with confidence 0.5."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.tasks.data_ingestion import _async_ingest_investing, _event_measures


def test_blank_measures_are_not_defaults() -> None:
    assert _event_measures({}) is None
    assert _event_measures({"market_effect": "", "confidence": 0.2}) is None
    assert _event_measures({"market_effect": 0.0, "confidence": 0.5}) == (0.0, 0.5)


@pytest.mark.asyncio
async def test_blank_event_is_not_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    added: list[object] = []

    class Session:
        def add(self, row: object) -> None:
            added.append(row)

        async def commit(self) -> None:
            return None

        async def __aenter__(self) -> "Session":
            return self

        async def __aexit__(self, *_exc: object) -> bool:
            return False

    async def fetch(_symbols: list[str]) -> dict:
        return {
            "events": [
                {"event_name": "пусто"},
                {"event_name": "явное", "market_effect": 0.1, "confidence": 0.8, "event_date": "2026-01-02"},
            ],
            "earnings": [],
            "quotes": {},
        }

    monkeypatch.setattr("app.services.data.investing_rapidapi.is_configured", lambda: True)
    monkeypatch.setattr("app.services.data.investing_rapidapi.fetch_market_intelligence", fetch)
    monkeypatch.setattr("app.db.session.AsyncSessionLocal", lambda: Session())
    monkeypatch.setattr(
        "app.services.macro.client._parse_dt",
        lambda _value: datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    result = await _async_ingest_investing(["SBER"])
    assert result["stored"] == 1
    assert len(added) == 1
    assert added[0].market_effect == 0.1
    assert added[0].confidence == 0.8
