"""GA16-250: correlation sees the sized share count, not a fake quantity of 1."""
from __future__ import annotations

from types import SimpleNamespace

from app.services.risk.maneuver_bot_guard import snapshot_with_selected


def test_selected_maneuver_keeps_real_share_count() -> None:
    sized = SimpleNamespace(
        ticker="SBER",
        risk=SimpleNamespace(position_size_usd=450.0, position_size_shares=4.5),
    )
    empty = SimpleNamespace(
        ticker="GAZP",
        risk=SimpleNamespace(position_size_usd=0.0, position_size_shares=0.0),
    )
    snap = snapshot_with_selected(None, [sized, empty])
    by_ticker = {ref.data["config"]["ticker"]: ref.data["runtime"]["position_qty"] for ref in snap.bots}
    assert by_ticker["SBER"] == 4.5
    assert by_ticker["GAZP"] == 0.0
