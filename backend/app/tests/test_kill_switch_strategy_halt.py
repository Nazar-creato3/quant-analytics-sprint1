"""KillSwitch strategy halt integration — loop stops within one tick."""
from __future__ import annotations

import asyncio

import pytest

from app.services.control_fabric.strategy_halt import (
    REDIS_KILL_FLAG_PREFIX,
    check_strategy_halt_async,
    check_strategy_halt_sync,
)


@pytest.mark.asyncio
async def test_kill_switch_stops_infinite_loop_within_one_tick():
    ticks = 0
    halted_at: int | None = None
    session_prefs: dict = {"strategies_stopped": False}

    async def fake_loop() -> None:
        nonlocal ticks, halted_at
        while True:
            status = check_strategy_halt_sync(session_preferences=session_prefs)
            if status.halted:
                halted_at = ticks
                break
            ticks += 1
            if ticks == 5:
                session_prefs["strategies_stopped"] = True
            await asyncio.sleep(0)

    await asyncio.wait_for(fake_loop(), timeout=1.0)
    assert halted_at == 5


@pytest.mark.asyncio
async def test_redis_kill_flag_halts_async_loop(monkeypatch):
    async def fake_cache_get(key: str):
        if key == f"{REDIS_KILL_FLAG_PREFIX}:profile-1":
            return {"reason": "test halt"}
        return None

    monkeypatch.setattr(
        "app.services.control_fabric.strategy_halt.cache_get",
        fake_cache_get,
    )
    status = await check_strategy_halt_async(profile_id="profile-1")
    assert status.halted is True
    assert status.source == "redis_profile"
