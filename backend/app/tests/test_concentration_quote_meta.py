"""GA16-281: holdings quotes must not invent 2026-10-04 official closes."""
from __future__ import annotations

from datetime import date

from app.services.concentration import service as conc
from app.services.qa.feature_flags import reset_for_tests, set_global
from app.services.quant_math.book import PriceQuote


def setup_function() -> None:
    reset_for_tests()
    set_global("qa_concentration", True)


def test_quote_meta_comes_from_holding_not_hardcoded(monkeypatch) -> None:
    seen: list[PriceQuote] = []
    real = conc.PriceQuote

    def capture(*args: object, **kwargs: object) -> PriceQuote:
        quote = real(*args, **kwargs)
        seen.append(quote)
        return quote

    monkeypatch.setattr(conc, "PriceQuote", capture)
    conc.analyze_holdings(
        [
            {
                "ticker": "SBER",
                "qty": "1",
                "price": "100",
                "ccy": "RUB",
                "as_of": "2025-06-01",
                "price_type": "last_available",
            }
        ]
    )
    assert seen[0].as_of == date(2025, 6, 1)
    assert seen[0].price_type == "last_available"
    assert seen[0].as_of != date(2026, 10, 4)


def test_missing_meta_is_today_and_not_official_close(monkeypatch) -> None:
    seen: list[PriceQuote] = []
    real = conc.PriceQuote

    def capture(*args: object, **kwargs: object) -> PriceQuote:
        quote = real(*args, **kwargs)
        seen.append(quote)
        return quote

    monkeypatch.setattr(conc, "PriceQuote", capture)
    conc.analyze_holdings([{"ticker": "SBER", "qty": "1", "price": "100", "ccy": "RUB"}])
    assert seen[0].as_of == date.today()
    assert seen[0].price_type == "last_available"
