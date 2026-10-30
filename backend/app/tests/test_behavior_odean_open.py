"""GA16-299: disposition uses open + closed outcomes, not sell-win share."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.behavior.service import analyze_trades
from app.services.qa.feature_flags import reset_for_tests


def setup_function() -> None:
    reset_for_tests()


def teardown_function() -> None:
    reset_for_tests()


def test_paper_gain_lowers_pgr() -> None:
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    trades = []
    # Eight full winning roundtrips (enough sample)...
    t = t0
    for _ in range(7):
        trades.append({"ticker": "SBER", "side": "buy", "qty": 1, "price": 100, "time": t})
        t += timedelta(days=5)
        trades.append({"ticker": "SBER", "side": "sell", "qty": 1, "price": 110, "time": t})
        t += timedelta(days=1)
    # ...plus one win and one open paper gain on LKOH marked by last sell print
    trades.append({"ticker": "LKOH", "side": "buy", "qty": 2, "price": 100, "time": t})
    t += timedelta(days=5)
    trades.append({"ticker": "LKOH", "side": "sell", "qty": 1, "price": 120, "time": t})
    out = analyze_trades(trades)
    assert out["insufficient"] is False
    assert out["realized_gains"] == 8
    assert out["paper_gains"] == 1
    assert out["realized_gain_share"] == 8 / 9
