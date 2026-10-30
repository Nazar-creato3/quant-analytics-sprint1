"""What to do when a horizon expires: paper book vs live order vs filled trade."""
from __future__ import annotations

from typing import Any

from app.services.portfolio.position_analytics import should_auto_close_on_horizon


def is_paper_maneuver(maneuver: Any) -> bool:
    mode = str(getattr(maneuver, "trading_mode", None) or "paper").lower()
    return mode != "live"


def has_fill(maneuver: Any) -> bool:
    status = str(getattr(maneuver, "status", "") or "").lower()
    if status == "filled":
        return True
    price = getattr(maneuver, "fill_price", None)
    try:
        return price is not None and float(price) > 0
    except (TypeError, ValueError):
        return False


def expire_disposition(maneuver: Any) -> str:
    """close_and_audit | close_paper_and_audit | cancel_live_no_audit | skip"""
    if not should_auto_close_on_horizon(maneuver):
        return "skip"
    if has_fill(maneuver):
        return "close_and_audit"
    if is_paper_maneuver(maneuver):
        return "close_paper_and_audit"
    return "cancel_live_no_audit"
