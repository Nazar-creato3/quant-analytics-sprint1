"""GA16-259: a missing quote must not fill a grid from the daily close."""
from __future__ import annotations

import pytest

from app.tasks.grid import _async_tick_grid_bots


@pytest.mark.asyncio
async def test_missing_quote_does_not_fill_from_daily_close(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = {
        "is_active": True,
        "is_paused": False,
        "config": {"ticker": "SBER"},
        "total_trades": 0,
    }
    ticks: list[float] = []
    bar_calls: list[str] = []

    class Halt:
        halted = False
        reason = ""
        source = ""

    class Bar:
        close = 100.0

    async def halt() -> Halt:
        return Halt()

    async def load_grid() -> dict:
        return {"g1": dict(bot)}

    async def save_grid(_bots: dict) -> None:
        return None

    async def load_bots(_key: str, _memory: dict) -> dict:
        return {}

    async def save_bots(_key: str, _memory: dict, _bots: dict) -> None:
        return None

    async def no_quote(_ticker: str) -> dict:
        return {}

    async def bars(_session: object, ticker: str, _interval: str, _limit: int) -> list[Bar]:
        bar_calls.append(ticker)
        return [Bar()]

    def apply_tick(data: dict, price: float, **_kwargs: object) -> dict:
        ticks.append(price)
        data = dict(data)
        data["total_trades"] = 1
        return data

    async def cache_set(*_args: object, **_kwargs: object) -> None:
        return None

    async def done(value: object) -> object:
        return value

    monkeypatch.setattr("app.services.control_fabric.strategy_halt.check_strategy_halt_async", halt)
    monkeypatch.setattr("app.api.v1.endpoints.grid._load_all_bots", load_grid)
    monkeypatch.setattr("app.api.v1.endpoints.grid._save_all_bots", save_grid)
    monkeypatch.setattr("app.services.bots.store.load_bots", load_bots)
    monkeypatch.setattr("app.services.bots.store.save_bots", save_bots)
    monkeypatch.setattr("app.services.market_data.client.get_grid_tick_quote", no_quote)
    monkeypatch.setattr("app.services.market_data.bars.get_bars_for_chart", bars)
    monkeypatch.setattr("app.services.grid.tick.apply_price_tick", apply_tick)
    monkeypatch.setattr("app.utils.cache.cache_set", cache_set)
    monkeypatch.setattr(
        "app.services.bot_risk.guard.run_portfolio_circuit_breaker",
        lambda **_kwargs: done(None),
    )
    monkeypatch.setattr("app.services.bot_risk.guard.load_peak_pnl", lambda: done(0.0))
    monkeypatch.setattr(
        "app.services.bot_risk.guard.build_snapshot_from_stores",
        lambda **_kwargs: None,
    )

    result = await _async_tick_grid_bots()
    assert bar_calls == []
    assert ticks == []
    assert result["updated"] == 0
    assert result["fills"] == 0
