"""GA16-260: short SPY history must not be replaced by a random series."""
from __future__ import annotations

import pytest

from app.tasks.forecast import _async_register_chronos_member


@pytest.mark.asyncio
async def test_short_spy_history_is_not_a_random_series(monkeypatch: pytest.MonkeyPatch) -> None:
    class Session:
        async def __aenter__(self) -> "Session":
            return self

        async def __aexit__(self, *_exc: object) -> bool:
            return False

    async def no_bars(_session: object, _ticker: str, _interval: str, _limit: int, **_kwargs: object) -> list:
        return []

    def refuse_component() -> None:
        raise AssertionError("model must not run without history")

    monkeypatch.setattr("app.db.session.AsyncSessionLocal", lambda: Session())
    monkeypatch.setattr("app.services.market_data.bars.get_bars_for_chart", no_bars)
    monkeypatch.setattr("app.services.forecast.chronos_component.get_chronos_component", refuse_component)

    result = await _async_register_chronos_member()
    assert result["reason"] == "нет данных"
    assert result["registered"] is False
    assert result["chronos_live"] is False
