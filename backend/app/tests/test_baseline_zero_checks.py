"""GA16-261: zero scored checks must not publish the baseline as live."""
from __future__ import annotations

import pytest

from app.tasks.forecast import _async_register_live_baseline


@pytest.mark.asyncio
async def test_zero_checks_do_not_promote_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    class Row:
        n = 0
        acc = None

    class Result:
        def one(self) -> Row:
            return Row()

    class Session:
        async def __aenter__(self) -> "Session":
            return self

        async def __aexit__(self, *_exc: object) -> bool:
            return False

        async def execute(self, _stmt: object) -> Result:
            return Result()

    class Store:
        backend = "memory"

        def materialize_from_prices(self, *_args: object, **_kwargs: object) -> None:
            return None

    promoted: list[bool] = []

    def register(**kwargs: object) -> bool:
        promoted.append(bool(kwargs.get("promote_live")))
        return True

    async def no_bars(*_args: object, **_kwargs: object) -> list:
        return []

    monkeypatch.setattr("app.db.session.AsyncSessionLocal", lambda: Session())
    monkeypatch.setattr("app.services.forecast.feature_store.get_forecast_feature_store", lambda: Store())
    monkeypatch.setattr("app.services.market_data.bars.get_bars_for_chart", no_bars)
    monkeypatch.setattr("app.services.forecast.mlflow_registry.register_ensemble_run", register)

    result = await _async_register_live_baseline()
    assert promoted == []
    assert result["registered"] is False
    assert result["reason"] == "нет данных"
