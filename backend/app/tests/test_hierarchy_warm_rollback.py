"""One failing ticker in the hierarchy warm-up must not poison the rest of the batch."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.risk import hierarchy_intervals as hi


@pytest.mark.asyncio
async def test_rollback_after_failure(monkeypatch) -> None:
    db = AsyncMock()
    calls = []

    async def resolve(_db, sym):
        calls.append(sym)
        if sym == "BAD":
            raise RuntimeError("flush failed")
        return SimpleNamespace(id=1, symbol=sym)

    monkeypatch.setattr("app.services.instrument.resolver.resolve_or_create_instrument", resolve)
    monkeypatch.setattr(hi, "load_interval_for_instrument", AsyncMock(return_value=None))
    monkeypatch.setattr(hi, "get_cached_forecast", AsyncMock(return_value=None))
    monkeypatch.setattr("app.services.risk.hierarchy_hints.hint_from_cached_forecast", lambda s, c: SimpleNamespace(cache_hit=False))
    hints, _ = await hi.warm_missing_hierarchy_hints(db, ["BAD", "SBER"], {}, {})
    assert calls == ["BAD", "SBER"]
    assert "SBER" in hints
    db.rollback.assert_awaited()
