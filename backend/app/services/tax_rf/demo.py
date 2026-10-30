"""Demo lots for K3 golden tests. Not live broker data.

Manual answers: docs/qa/evidence/k3/manual-calc.md
Rates: target_portfolio.tax (OQ-36-1, check date 2026-10-06).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.target_portfolio.types import TaxLot

# As-of for demo marks and LTH calendar (fixed for reproducibility).
DEMO_AS_OF = date(2026, 10, 14)
DEMO_YEAR = 2026

# Open lots (paper). Marks used only for "sell today" estimates.
OPEN_LOTS: list[TaxLot] = [
    TaxLot(
        lot_id="sber-1",
        ticker="SBER",
        qty=Decimal("100"),
        cost=Decimal("20000.00"),
        acquired=date(2023, 1, 15),
    ),
    TaxLot(
        lot_id="loss-1",
        ticker="GAZP",
        qty=Decimal("50"),
        cost=Decimal("5000.00"),
        acquired=date(2026, 3, 1),
    ),
]

# Marks (RUB total for the open qty). Source: fixture.
MARKS: dict[str, Decimal] = {
    "SBER": Decimal("28000.00"),  # +8000 vs cost
    "GAZP": Decimal("3500.00"),  # -1500 vs cost
}

# Realized YTD row shape matches fifo_realize output (already closed).
REALIZED_YTD: list[dict[str, str]] = [
    {
        "lot_id": "vtbr-closed",
        "ticker": "VTBR",
        "qty": "1000.00",
        "proceeds": "1500000.00",
        "cost": "500000.00",
        "result": "1000000.00",
        "acquired": "2025-06-01",
        "sold_on": "2026-05-10",
        "year": "2026",
        "full_years": "0",
        "long_term": "false",
    }
]

DEMO_IIS = {
    "account_type": "iis",
    "opened_on": date(2022, 4, 1),
    "contribution": Decimal("400000.00"),
}
