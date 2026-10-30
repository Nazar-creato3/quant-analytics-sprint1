"""GA16-279: bonds, payouts, and liquidity stay off without a ready status."""
from __future__ import annotations

from app.services.decision_core.map import from_bonds, from_liquidity, from_payouts


def test_missing_status_is_not_marked_ready() -> None:
    assert from_bonds({"summary": {"duration": "3.2"}}) is None
    assert from_payouts({"passive_declared_net_12m": "1000"}) is None
    assert from_liquidity({"share_1d": "0.1"}) is None


def test_ready_status_keeps_the_signal() -> None:
    bonds = from_bonds({"summary": {"duration": "3.2"}, "data_status": "ok"})
    assert bonds is not None
    assert bonds["data_status"] == "ok"
    payouts = from_payouts({"passive_declared_net_12m": "1000", "data_status": "частично"})
    assert payouts is not None
    liquidity = from_liquidity({"share_1d": "0.1", "data_status": "ok"})
    assert liquidity is not None
