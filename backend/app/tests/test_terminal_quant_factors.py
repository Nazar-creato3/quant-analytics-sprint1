"""GA16-314: quant factors must not invent portfolio exposure without a book."""
from __future__ import annotations

from app.services.terminal_platform.market.factors import build_quant_factors
from app.services.terminal_platform.market.schemas import PortfolioSummaryBlock


def test_ga16_314_no_invented_portfolio_factor_without_book():
    rows = build_quant_factors(portfolio=None)
    assert all(r.name != "Portfolio exposure" for r in rows)
    assert not any(abs((r.weight or 0) - 0.15) < 1e-9 and r.contribution == 0.0 for r in rows)


def test_ga16_314_with_positions_keeps_exposure_factor():
    book = PortfolioSummaryBlock(
        has_positions=True,
        exposure_pct=40.0,
        open_positions=2,
        concentration_pct=None,
        as_of=None,
    )
    rows = build_quant_factors(portfolio=book)
    names = {r.name for r in rows}
    assert "Portfolio exposure" in names
