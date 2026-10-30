"""Shared capital slots: forecast / grid / cash. Never increase a slot by borrowing another."""

from __future__ import annotations

from typing import Any

# Residual cash is not a trading slot.
SLOT_WEIGHTS = {
    "forecast": 0.45,
    "grid": 0.35,
    "cash": 0.20,
}


def slot_cap_usd(portfolio_usd: float, slot: str) -> float:
    weight = SLOT_WEIGHTS.get(slot, 0.0)
    return max(0.0, float(portfolio_usd) * weight)


def slot_room_usd(portfolio_usd: float, slot: str, used_usd: float) -> float:
    return max(0.0, slot_cap_usd(portfolio_usd, slot) - max(0.0, float(used_usd)))


def grid_capital_used(bots: dict[str, Any] | None, *, owner_email: str | None = None) -> float:
    used = 0.0
    for raw in (bots or {}).values():
        if not isinstance(raw, dict):
            continue
        if owner_email and str(raw.get("created_by") or "") != owner_email:
            continue
        if raw.get("is_active") is False:
            continue
        cfg = raw.get("config") or {}
        used += float(cfg.get("total_capital") or 0.0)
    return used
