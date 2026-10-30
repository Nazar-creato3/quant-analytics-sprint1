"""Honest paper vs live capability matrix for Robot Core (variant A)."""
from __future__ import annotations

from typing import Any

LIVE_ACTIONS = ("entry", "sl", "tp")
PAPER_ONLY_ACTIONS = ("trail", "partial", "add")
ALL_PAPER = ("entry", "sl", "tp", "trail", "partial", "add")


class FeatureNotAvailableInLiveMode(Exception):
    """Raised when a paper-only feature is requested on a live plan."""

    def __init__(self, action: str):
        self.action = action
        super().__init__(f"FeatureNotAvailableInLiveMode: {action}")


def default_capabilities(mode: str = "paper") -> dict[str, Any]:
    mode_n = (mode or "paper").lower()
    if mode_n == "live":
        return {
            "mode": "live",
            "live": list(LIVE_ACTIONS),
            "paper": list(PAPER_ONLY_ACTIONS),
            "note": "Live = entry+SL/TP brackets only; trail/partial/add are paper-only until venue sync.",
        }
    return {
        "mode": "paper",
        "live": list(LIVE_ACTIONS),
        "paper": list(ALL_PAPER),
        "note": "Paper LevelMonitor executes full matrix.",
    }


def assert_action_allowed(*, mode: str, action: str) -> None:
    """Block paper-only actions on live plans."""
    mode_n = (mode or "paper").lower()
    act = (action or "").lower()
    if mode_n != "live":
        return
    if act in PAPER_ONLY_ACTIONS or act in {"trail", "partial", "add", "tp_partial"}:
        raise FeatureNotAvailableInLiveMode(act)


def capabilities_for_plan(plan: Any) -> dict[str, Any]:
    stored = getattr(plan, "capabilities", None)
    if isinstance(stored, dict) and stored.get("mode"):
        return stored
    return default_capabilities(str(getattr(plan, "mode", "paper") or "paper"))
