"""One platform snapshot for the AM desk UI — computed, not a planner stub."""
from __future__ import annotations

from typing import Any

from app.services.platform_desk.mandate import load_ips
from app.services.platform_desk.monitor import load_snapshot, persist_snapshot, snapshot
from app.services.platform_desk.promotion import research_queue
from app.services.platform_desk.reporting import build_client_pack, load_latest_client_pack
from app.services.platform_desk.runbook import desks


def evaluate_platform(*, user_id: str = "paper", refresh_monitor: bool = False) -> dict[str, Any]:
    pack = load_latest_client_pack(user_id=user_id)
    if pack is None:
        try:
            from app.services.forecast.daily_book import excess_history, load_book

            book = load_book()
            pack = build_client_pack(book=book, realized=book, excess_hist=excess_history())
            pack["user_id"] = str(user_id)
        except Exception:
            pack = {
                "tear": {"n": 0, "note": "no_book"},
                "brinson": {},
                "risk_contribution": [],
                "user_id": str(user_id),
            }
    mon = (
        persist_snapshot(user_id=user_id)
        if refresh_monitor
        else (load_snapshot(user_id=user_id) or {**snapshot(), "user_id": str(user_id)})
    )
    return {
        "report": pack,
        "ips": load_ips(user_id).to_dict(),
        "monitor": mon,
        "promotion": research_queue(reviewer=user_id),
        "desks": desks(),
    }
