"""GA16-258: a missing quote must not tick a bot on the previous price."""
from __future__ import annotations

import pytest

from app.tasks.strategy_bots import _async_tick_strategy_bots


@pytest.mark.asyncio
async def test_missing_quote_does_not_reuse_last_price(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = {
        "is_active": True,
        "is_paused": False,
        "config": {"ticker": "SBER"},
        "runtime": {"last_price": 250.0},
    }
    ticks: list[float] = []

    class Halt:
        halted = False
        reason = ""

    async def halt() -> Halt:
        return Halt()

    async def empty_grid() -> dict:
        return {}

    async def save_grid(_bots: dict) -> None:
        return None

    async def load_bots(key: str, _memory: dict) -> dict:
        if key == "dca:bots":
            return {"b1": dict(bot)}
        return {}

    async def save_bots(_key: str, _memory: dict, _bots: dict) -> None:
        return None

    async def no_quote(_ticker: str) -> dict:
        return {}

    def apply_dca(data: dict, price: float, **_kwargs: object) -> dict:
        ticks.append(price)
        return data

    def apply_mom(data: dict, price: float, **_kwargs: object) -> dict:
        ticks.append(price)
        return data

    monkeypatch.setattr("app.services.control_fabric.strategy_halt.check_strategy_halt_async", halt)
    monkeypatch.setattr("app.api.v1.endpoints.grid._load_all_bots", empty_grid)
    monkeypatch.setattr("app.api.v1.endpoints.grid._save_all_bots", save_grid)
    monkeypatch.setattr("app.services.bots.store.load_bots", load_bots)
    monkeypatch.setattr("app.services.bots.store.save_bots", save_bots)
    monkeypatch.setattr("app.services.market_data.client.get_grid_tick_quote", no_quote)
    monkeypatch.setattr("app.services.bots.dca.apply_dca_tick", apply_dca)
    monkeypatch.setattr("app.services.bots.momentum.apply_momentum_tick", apply_mom)
    monkeypatch.setattr(
        "app.services.bot_risk.guard.run_portfolio_circuit_breaker",
        lambda **_kwargs: _done(None),
    )
    monkeypatch.setattr("app.services.bot_risk.guard.load_peak_pnl", lambda: _done(0.0))
    monkeypatch.setattr(
        "app.services.bot_risk.guard.build_snapshot_from_stores",
        lambda **_kwargs: None,
    )

    result = await _async_tick_strategy_bots()
    assert ticks == []
    assert result["updated"] == 0
    assert result["status"] == "ok"


async def _done(value: object) -> object:
    return value
