"""UI feature gates — removed screens return HTTP 410 on their read APIs."""
from __future__ import annotations

from fastapi import HTTPException, status

REMOVED_UI_FEATURES = frozenset({"pilot", "backtest", "audit_log"})


def raise_if_ui_removed(feature: str) -> None:
    """Raise 410 Gone when a deprecated UI feature API is called."""
    if feature in REMOVED_UI_FEATURES:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"The {feature.replace('_', ' ')} feature has been removed from this deployment.",
        )
