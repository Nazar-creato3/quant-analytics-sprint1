"""Nightly AM pack: client report + monitor snapshot. Called from realize + celery."""
from __future__ import annotations

from typing import Any, Mapping


def run_nightly_platform(
    *,
    book: Mapping[str, Any] | None = None,
    realized: Mapping[str, Any] | None = None,
    asset_returns: Mapping[str, float] | None = None,
    user_id: str = "paper",
) -> dict[str, Any]:
    from app.services.forecast.daily_book import excess_history, load_book
    from app.services.platform_desk.monitor import persist_snapshot
    from app.services.platform_desk.reporting import build_client_pack, persist_client_pack

    live_book = book if book is not None else load_book()
    live_real = realized if realized is not None else live_book
    pack = build_client_pack(
        book=live_book,
        realized=live_real,
        excess_hist=excess_history(),
        asset_returns=asset_returns,
    )
    pack["user_id"] = str(user_id)
    persist_client_pack(pack, user_id=user_id)
    mon = persist_snapshot(user_id=user_id)
    return {"report": pack, "monitor": mon}
