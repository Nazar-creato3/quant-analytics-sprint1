"""Live venue brackets from RobotPlan levels.

Extracts SL/TP for OrderRouter bracket legs. Does not invent orders —
only maps plan truth into existing adapter bracket fields.
"""
from __future__ import annotations

from typing import Any


def brackets_from_levels(
    levels: list[dict[str, Any]] | None,
    *,
    entry: float | None = None,
    atr: float | None = None,
    side: str = "long",
    portfolio_size: float | None = None,
) -> dict[str, float | None]:
    """Return stop_loss / take_profit prices from active plan levels."""
    sl: float | None = None
    tp: float | None = None
    for lv in levels or []:
        kind = str(lv.get("kind") or "")
        status = str(lv.get("status") or "")
        if status in {"filled", "cancelled", "triggered"}:
            continue
        price = lv.get("price")
        try:
            px = float(price) if price is not None else None
        except (TypeError, ValueError):
            px = None
        if px is None or px <= 0:
            continue
        if kind == "sl" and sl is None:
            sl = px
        elif kind == "tp" and tp is None:
            # First (highest-ROI / primary) TP for venue bracket
            tp = px
        elif kind == "trail" and status == "armed" and sl is None:
            sl = px
    raw = {"stop_loss": sl, "take_profit": tp}
    if entry and atr and portfolio_size:
        from app.services.execution.bracket_risk import align_with_engine

        chk = align_with_engine(
            ticker="BRACKET",
            side=side,
            entry=float(entry),
            atr=float(atr),
            stop_loss=sl,
            take_profit=tp,
            portfolio_size=float(portfolio_size),
        )
        raw["stop_loss"] = chk.stop_loss if chk.ok else sl
        raw["take_profit"] = chk.take_profit if chk.ok else tp
        raw["aligned"] = chk.aligned
        raw["bracket_ok"] = chk.ok
    return raw
