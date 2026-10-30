"""Strategy execution halt checks — KillSwitch consumer for running loops."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.utils.cache import cache_get

REDIS_KILL_FLAG_PREFIX = "kill_switch:strategies_stopped"
REDIS_SYSTEM_KILL_FLAG = "kill_switch:system:active"


@dataclass(frozen=True, slots=True)
class StrategyHaltStatus:
    """Result of a per-tick halt poll."""

    halted: bool
    reason: str | None = None
    source: str | None = None


def _session_prefs_halted(
    session_preferences: dict[str, Any] | None,
    *,
    sleeve_id: str | None = None,
) -> StrategyHaltStatus:
    prefs = session_preferences or {}
    if prefs.get("strategies_stopped"):
        return StrategyHaltStatus(
            halted=True,
            reason=str(prefs.get("strategies_stop_reason") or "kill_switch"),
            source="session_preferences",
        )
    if sleeve_id:
        stopped_sleeves = set(prefs.get("stopped_sleeve_ids") or [])
        if sleeve_id in stopped_sleeves:
            return StrategyHaltStatus(
                halted=True,
                reason=str(prefs.get("strategies_stop_reason") or "sleeve kill_switch"),
                source="stopped_sleeve_ids",
            )
    if prefs.get("session_killed"):
        return StrategyHaltStatus(
            halted=True,
            reason="session_killed",
            source="session_preferences",
        )
    return StrategyHaltStatus(halted=False)


async def check_strategy_halt_async(
    *,
    profile_id: str | None = None,
    sleeve_id: str | None = None,
    session_preferences: dict[str, Any] | None = None,
) -> StrategyHaltStatus:
    """Poll session preferences and Redis kill flags every strategy tick."""
    prefs_status = _session_prefs_halted(session_preferences, sleeve_id=sleeve_id)
    if prefs_status.halted:
        return prefs_status

    system_flag = await cache_get(REDIS_SYSTEM_KILL_FLAG)
    if system_flag:
        return StrategyHaltStatus(
            halted=True,
            reason=str(system_flag.get("reason") or "system kill_switch"),
            source="redis_system",
        )

    if profile_id:
        profile_flag = await cache_get(f"{REDIS_KILL_FLAG_PREFIX}:{profile_id}")
        if profile_flag:
            return StrategyHaltStatus(
                halted=True,
                reason=str(profile_flag.get("reason") or "profile kill_switch"),
                source="redis_profile",
            )

    if sleeve_id:
        sleeve_flag = await cache_get(f"{REDIS_KILL_FLAG_PREFIX}:sleeve:{sleeve_id}")
        if sleeve_flag:
            return StrategyHaltStatus(
                halted=True,
                reason=str(sleeve_flag.get("reason") or "sleeve kill_switch"),
                source="redis_sleeve",
            )

    return StrategyHaltStatus(halted=False)


def check_strategy_halt_sync(
    *,
    session_preferences: dict[str, Any] | None = None,
    sleeve_id: str | None = None,
) -> StrategyHaltStatus:
    """Synchronous halt check for offline validation loops (session prefs only)."""
    return _session_prefs_halted(session_preferences, sleeve_id=sleeve_id)
