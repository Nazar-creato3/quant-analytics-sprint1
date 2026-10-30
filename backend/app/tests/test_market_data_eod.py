from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.market_data.eod import EodRow, MissingOfficialClose, get_eod_price
from app.services.market_data.license import ISS_DELAY_LABEL, quote_envelope
from app.services.market_data.series import Action, Bar, get_series


def _row(**kwargs) -> EodRow:
    base = dict(
        instrument_id="SBER",
        session_date=date(2024, 1, 31),
        official_close=Decimal("100"),
        last_close=Decimal("101"),
        volume=Decimal("1"),
        source="iss_moex",
        board="TQBR",
        license_tag="internal_only",
        as_of=date(2024, 1, 31),
    )
    base.update(kwargs)
    return EodRow(**base)


def test_valuation_uses_official_never_last():
    price, note = get_eod_price(_row(), purpose="valuation")
    assert price == Decimal("100")
    assert note == "official_close"
    with pytest.raises(MissingOfficialClose):
        get_eod_price(_row(official_close=None), purpose="valuation")


def test_display_falls_back_to_last_with_flag():
    price, note = get_eod_price(_row(official_close=None), purpose="display")
    assert price == Decimal("101")
    assert note == "last_available_not_traded"


def test_untrusted_client_price_is_not_stamped_display_allowed():
    env = quote_envelope(
        symbol="SBER",
        price="100",
        source="iss_moex",
        as_of="2024-01-31",
        delayed=True,
        audience="public",
        trusted_price=False,
    )
    assert env["price"] is None
    assert env["display_allowed"] is False
    assert env["license_tag"] == "нет данных"
    assert env["freshness_label"] == "нет данных"


def test_envelope_always_has_license_tag():
    env = quote_envelope(
        symbol="SBER",
        price="100",
        source="iss_moex",
        as_of="2024-01-31",
        delayed=True,
        audience="public",
    )
    assert env["license_tag"] == "display_allowed"
    assert env["display_allowed"] is True
    assert env["price"] == "100"
    assert env["freshness_label"] == ISS_DELAY_LABEL


def test_binance_beta_visible():
    env = quote_envelope(
        symbol="BTC-USD",
        price="10",
        source="binance_public",
        as_of="2024-01-31",
        delayed=False,
        audience="owner",
    )
    assert env["license_tag"] == "beta"
    assert env["price"] == "10"


def test_split_and_dividend_series():
    bars = [
        Bar(date(2024, 1, 1), Decimal("100")),
        Bar(date(2024, 1, 2), Decimal("10")),
        Bar(date(2024, 1, 3), Decimal("10")),
    ]
    actions = [
        Action(date(2024, 1, 2), "split", factor=Decimal("10")),
        Action(date(2024, 1, 3), "dividend", cash=Decimal("1")),
    ]
    raw = get_series(bars, actions, "raw")
    assert raw[1].close == Decimal("10")
    adj = get_series(bars, actions, "split_adj")
    assert adj[0].close == Decimal("10")
    tr = get_series(bars, actions, "total_return")
    assert tr[-1].close > Decimal("10")
