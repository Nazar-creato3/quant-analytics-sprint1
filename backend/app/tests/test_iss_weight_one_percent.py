"""GA16-289: ISS weight 1 means 1%, not 100%."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.fund_lookthrough.parsers import parse_iss_analytics


def test_one_percent_is_not_full_weight() -> None:
    out = parse_iss_analytics(
        {
            "columns": ["secid", "weight"],
            "data": [["SBER", 1], ["GAZP", 2]],
        },
        index_code="IMOEX",
        as_of=date(2026, 1, 15),
        source_url="https://example.test",
    )
    by_isin = {h["holding_isin"]: Decimal(h["weight"]) for h in out["holdings"]}
    assert by_isin["SBER"] == Decimal("0.01")
    assert by_isin["GAZP"] == Decimal("0.02")


def test_fraction_below_one_kept() -> None:
    out = parse_iss_analytics(
        {
            "columns": ["secid", "weight"],
            "data": [["SBER", "0.05"]],
        },
        index_code="IMOEX",
        as_of=date(2026, 1, 15),
        source_url="https://example.test",
    )
    assert Decimal(out["holdings"][0]["weight"]) == Decimal("0.05")
