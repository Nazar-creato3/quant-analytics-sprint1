"""Shared NDFL rates for K3 consumers (bonds coupons, etc.).

Single source: ``target_portfolio.tax`` (founder figures 2026-10-07, OQ-36-1).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.qa.feature_flags import is_enabled
from app.services.target_portfolio.tax import (
    NDFL_RATE_LABEL,
    RESIDENT_BRACKET_RUB,
    RESIDENT_RATE_ABOVE_BRACKET,
    RESIDENT_RATE_UP_TO_BRACKET,
    ndfl_cash,
)

# Fallback while K3 flag is off (bonds prompt 56): flat 13% with note.
_FALLBACK_COUPON = Decimal("0.13")


def rates_snapshot() -> dict[str, Any]:
    return {
        "bracket_rub": str(RESIDENT_BRACKET_RUB),
        "rate_up_to": str(RESIDENT_RATE_UP_TO_BRACKET),
        "rate_above": str(RESIDENT_RATE_ABOVE_BRACKET),
        "label": NDFL_RATE_LABEL,
        "methodology": "/methodology/tax",
        "lawyer_gate": "[ЮРИСТ]",
        "k3_enabled": is_enabled("qa_k3_tax"),
    }


def coupon_ndfl_rate(*, ytd_taxable: Decimal | None = None) -> dict[str, str | None]:
    """Rate for coupon netting. Uses 13%/15% when K3 is on; else 13% with note."""
    if not is_enabled("qa_k3_tax"):
        return {
            "rate": str(_FALLBACK_COUPON),
            "note": "K3 не готов: 13% с пометкой",
            "tax_cash": None,
        }
    base = ytd_taxable if ytd_taxable is not None else Decimal("0")
    # Marginal rate for the next ruble of coupon income for a resident.
    if base >= RESIDENT_BRACKET_RUB:
        rate = RESIDENT_RATE_ABOVE_BRACKET
    else:
        rate = RESIDENT_RATE_UP_TO_BRACKET
    return {
        "rate": str(rate),
        "note": NDFL_RATE_LABEL,
        "tax_cash": None if ytd_taxable is None else format(ndfl_cash(base, resident=True, income="dividends"), "f"),
    }
