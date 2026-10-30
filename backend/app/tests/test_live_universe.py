"""«Боевой» with only T-Bank/Finam connected: maneuvers only for MOEX tickers."""
from app.services.pipeline import live_universe as lu


def test_moex_brokers_keep_moex_only(monkeypatch):
    monkeypatch.setattr(lu, "is_moex", lambda t: t in {"SBER", "GAZP", "IMOEX"})
    wl = ["SBER", "AAPL", "GAZP", "XLK", "IMOEX"]
    assert lu.restrict_to_brokers(wl, {"tinkoff"}) == ["SBER", "GAZP", "IMOEX"]
    assert lu.restrict_to_brokers(wl, {"tinkoff", "finam"}) == ["SBER", "GAZP", "IMOEX"]


def test_other_venue_or_none_keeps_all(monkeypatch):
    monkeypatch.setattr(lu, "is_moex", lambda t: t == "SBER")
    wl = ["SBER", "AAPL"]
    assert lu.restrict_to_brokers(wl, {"tinkoff", "alpaca"}) == wl
    assert lu.restrict_to_brokers(wl, set()) == wl
