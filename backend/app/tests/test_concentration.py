"""Prompt 14: weights vs independent calc; hidden overlaps."""
from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.services.concentration.service import analyze_holdings
from app.services.qa.feature_flags import reset_for_tests
from app.services.quant_math.book import Position, PriceQuote, weights_and_hhi
from datetime import date


def setup_function() -> None:
    reset_for_tests()


def teardown_function() -> None:
    reset_for_tests()


def _independent(holdings: list[dict]) -> tuple[dict[str, Decimal], Decimal]:
    positions = [
        Position(symbol=h["ticker"], qty=Decimal(str(h["qty"])), ccy=h["ccy"], instrument="equity")
        for h in holdings
    ]
    quotes = {
        h["ticker"]: PriceQuote(
            symbol=h["ticker"],
            as_of=date(2026, 10, 4),
            price=Decimal(str(h["price"])),
            ccy=h["ccy"],
            source="t",
            price_type="official_close",
        )
        for h in holdings
    }
    return weights_and_hhi(positions, quotes, {}, Decimal("0"))


def test_three_portfolios_match_quant_math():
    books = [
        [{"ticker": "SBER", "qty": "10", "price": "100", "ccy": "RUB"}],
        [
            {"ticker": "SBER", "qty": "60", "price": "100", "ccy": "RUB"},
            {"ticker": "GAZP", "qty": "40", "price": "100", "ccy": "RUB"},
        ],
        [
            {"ticker": "AAPL", "qty": "1", "price": "200", "ccy": "USD"},
            {"ticker": "MSFT", "qty": "1", "price": "200", "ccy": "USD"},
            {"ticker": "BTC-USD", "qty": "1", "price": "100", "ccy": "USD"},
        ],
    ]
    for holdings in books:
        got = analyze_holdings(holdings)
        w, hhi = _independent(holdings)
        assert got["hhi"] == str(hhi)
        for k, v in w.items():
            assert got["weights"][k] == str(v)
        assert "купите" not in got["disclaimer"].lower()
        assert got["hidden_risks"]["credit_rating"] == "нет данных"


def test_hidden_pref_and_token_overlap():
    pref = analyze_holdings(
        [
            {"ticker": "SBER", "qty": "10", "price": "1", "ccy": "RUB"},
            {"ticker": "SBERP", "qty": "10", "price": "1", "ccy": "RUB"},
        ]
    )
    assert any(o["via"] == "issuer" and set(o["tickers"]) == {"SBER", "SBERP"} for o in pref["hidden_overlaps"])
    assert Decimal(pref["by_issuer"]["SBER"]) == Decimal("1")
    token = analyze_holdings(
        [
            {"ticker": "AAPL", "qty": "1", "price": "10", "ccy": "USD"},
            {"ticker": "AAPLX", "qty": "1", "price": "10", "ccy": "USD"},
        ]
    )
    assert any("eq:AAPL" in o["asset_id"] or set(o["tickers"]) == {"AAPL", "AAPLX"} for o in token["hidden_overlaps"])


def test_api_empty():
    from app.tests.qa_session import bind_session_user, clear_session_user

    bind_session_user("nobody")
    client = TestClient(app)
    body = client.get("/api/v1/concentration", params={"user_id": "nobody"}).json()
    clear_session_user()
    assert body["empty"] is True
    assert body["source"] == "concentration"


def test_e46_06_hhi_nav_not_zero_rubles():
    got = analyze_holdings(
        [
            {"ticker": "SBER", "qty": "10", "price": "100", "ccy": "RUB"},
            {"ticker": "GAZP", "qty": "1", "price": "1000", "ccy": "RUB"},
        ]
    )
    assert got["nav"] == "2000"
    assert got["nav_ccy"] == "RUB"
    assert got["weights"]["SBER"] == got["weights"]["GAZP"]
    detail = got["explain"]["hhi"]["detail"]
    assert "Для портфеля 0 ₽" not in detail
    assert "2000" in detail


def test_e46_06_missing_price_is_not_one():
    got = analyze_holdings([{"ticker": "SBER", "qty": "10", "ccy": "RUB"}])
    assert "SBER" not in (got.get("weights") or {})
    assert got.get("data_status") == "нет данных"
