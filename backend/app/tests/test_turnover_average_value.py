"""GA16-292: turnover divisor is average value, not end value alone."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.services.decisions_report.service import _average_portfolio_value, _turnover


def _t(**kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


def test_average_is_midpoint_of_deposits_and_end() -> None:
    txns = [_t(kind="deposit", amount=Decimal("1000"), qty=Decimal("0"))]
    assert _average_portfolio_value(txns, Decimal("200")) == Decimal("600.00")


def test_turnover_not_inflated_by_low_end() -> None:
    txns = [
        _t(kind="deposit", amount=Decimal("1000"), qty=Decimal("0")),
        _t(
            kind="trade",
            amount=Decimal("800"),
            qty=Decimal("-8"),
            event_time=datetime(2024, 6, 1, tzinfo=timezone.utc),
        ),
    ]
    out = _turnover(txns, end=Decimal("200"))
    # sells/avg = 800/600 ≈ 1.3333; using end alone would be 800/200 = 4
    assert out["avg_value"] == Decimal("600.00")
    assert out["turnover"] == Decimal("1.3333")
    assert out["end_value"] == Decimal("200")
