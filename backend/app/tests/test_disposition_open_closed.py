"""GA16-291: PGR/PLR use realized + paper outcomes, not sell-win share."""
from __future__ import annotations

from decimal import Decimal

from app.services.decisions_report.service import _disposition


def test_pgr_includes_paper_gain() -> None:
    closed = [{"gain": True, "loss": False}]
    open_lots = {"SBER": [{"qty": Decimal("5"), "amount": Decimal("500")}]}
    marks = {"SBER": Decimal("120")}  # cost 100 → paper gain
    out = _disposition(closed, open_lots, marks)
    assert out["pgr"] == "0.5000"
    assert out["realized_gains"] == 1
    assert out["paper_gains"] == 1
    assert out["plr"] is None


def test_sell_share_alone_is_wrong() -> None:
    """Two winning sells + two paper gains: sell-share would be 1, Odean PGR is 0.5."""
    closed = [{"gain": True, "loss": False}, {"gain": True, "loss": False}]
    open_lots = {
        "GAZP": [{"qty": Decimal("2"), "amount": Decimal("200")}],
        "LKOH": [{"qty": Decimal("1"), "amount": Decimal("100")}],
    }
    marks = {"GAZP": Decimal("250"), "LKOH": Decimal("150")}
    out = _disposition(closed, open_lots, marks)
    assert out["pgr"] == "0.5000"
    assert out["realized_gains"] == 2
    assert out["paper_gains"] == 2
