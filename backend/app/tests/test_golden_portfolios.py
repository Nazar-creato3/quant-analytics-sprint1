"""Production book vs independent goldens (Prompt 01B)."""
from __future__ import annotations

import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.quant_math import (
    VaRMethod,
    apply_operations,
    expected_shortfall,
    money_weighted_return,
    portfolio_value,
    time_weighted_return,
    value_at_risk,
    weights_and_hhi,
)
from app.services.quant_math.book import PriceQuote

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / "docs" / "qa" / "golden"
sys.path.insert(0, str(REPO))
from validation.golden.independent import historical_var_percentile  # noqa: E402


def _goldens() -> list[Path]:
    return sorted(GOLDEN.glob("p*.json"))


@pytest.mark.parametrize("path", _goldens(), ids=lambda p: p.stem)
def test_golden_value_weights_returns(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = payload["expected"]
    book = apply_operations(payload["operations"])
    quotes = {
        row["symbol"]: PriceQuote(
            symbol=row["symbol"],
            as_of=date.fromisoformat(row["as_of"]),
            price=Decimal(row["price"]),
            ccy=row["ccy"],
            source=row["source"],
            price_type=row["price_type"],
        )
        for row in payload["quotes"]
    }
    fx = {ccy: Decimal(rate) for ccy, rate in payload["fx"].items()}
    value = portfolio_value(book.positions, quotes, fx, book.cash_base)
    assert abs(value - Decimal(expected["value"])) <= Decimal(expected["tolerance"]["value"])

    weights, hhi = weights_and_hhi(book.positions, quotes, fx, book.cash_base)
    for symbol, weight in expected["weights"].items():
        assert abs(weights[symbol] - Decimal(weight)) <= Decimal(expected["tolerance"]["weight"])
    assert abs(hhi - Decimal(expected["hhi"])) <= Decimal(expected["tolerance"]["hhi"])

    twr = time_weighted_return([(Decimal(a), Decimal(b)) for a, b in payload["twr_periods"]])
    assert abs(twr - Decimal(expected["twr"])) <= Decimal(expected["tolerance"]["twr"])

    mwr = money_weighted_return(
        [(date.fromisoformat(as_of), Decimal(amount)) for as_of, amount in payload["mwr_flows"]]
    )
    assert abs(mwr - Decimal(expected["mwr"])) <= Decimal(expected["tolerance"]["mwr"])


@pytest.mark.parametrize("path", _goldens(), ids=lambda p: p.stem)
def test_golden_var_independent_vs_quant_math(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    returns = payload["returns_window"]
    expected = payload["expected"]
    independent = historical_var_percentile(returns, 0.95)
    production = value_at_risk(returns, 0.95, method=VaRMethod.HISTORICAL)
    es = expected_shortfall(returns, 0.95, production)
    var_tol = float(expected["tolerance"]["var"])
    es_tol = float(expected["tolerance"]["es"])
    assert independent == pytest.approx(expected["var95"], abs=var_tol)
    assert production == pytest.approx(expected["var95_production"], abs=var_tol)
    # Rank (ceil) vs numpy percentile must stay distinct; a 0.05 blanket hid this.
    assert abs(production - independent) > var_tol
    assert es == pytest.approx(expected["es95"], abs=es_tol)
    assert es >= production - 1e-12
