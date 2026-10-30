"""GA16-290: empty composition currency/country must not become RUB/RU."""
from __future__ import annotations

from app.services.fund_lookthrough import store


def setup_function() -> None:
    store.reset()


def teardown_function() -> None:
    store.reset()


def test_missing_currency_country_are_unknown() -> None:
    store.upsert_yaml(
        {
            "fund_figi": "F1",
            "ticker": "FXUS",
            "as_of": "2026-01-15",
            "holdings": [{"holding_isin": "US0378331005", "weight": "0.1", "holding_name": "AAPL"}],
        }
    )
    rows = store.get_holdings("F1")
    assert rows is not None
    assert rows[0].currency == "unknown"
    assert rows[0].country == "unknown"


def test_explicit_currency_country_kept() -> None:
    store.upsert_yaml(
        {
            "fund_figi": "F2",
            "ticker": "FXDE",
            "as_of": "2026-01-15",
            "holdings": [
                {
                    "holding_isin": "DE000",
                    "weight": "0.2",
                    "currency": "EUR",
                    "country": "DE",
                }
            ],
        }
    )
    row = store.get_holdings("F2")[0]
    assert row.currency == "EUR"
    assert row.country == "DE"
