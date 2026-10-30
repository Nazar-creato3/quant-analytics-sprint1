"""GA16-285: broker view must not invent RUB/RU/fund when absent on the paper."""
from __future__ import annotations

from decimal import Decimal

from app.services.fund_lookthrough import service as svc


def test_broker_view_without_meta_uses_unknown(monkeypatch) -> None:
    monkeypatch.setattr(svc, "is_enabled", lambda _flag: True)
    monkeypatch.setattr(svc, "all_figi", lambda: ["FIGI1"])
    monkeypatch.setattr(svc, "resolve_figi", lambda _t: "FIGI1")
    monkeypatch.setattr(
        svc,
        "_holdings_from_book",
        lambda *_a, **_k: [{"ticker": "FXUS", "qty": 1}],
    )
    monkeypatch.setattr(svc, "_nav_weights", lambda *_a, **_k: [1.0])

    out = svc.lookthrough_portfolio("u1", mode="paper", by="currency", view="broker")
    assert out["data_status"] in {"ok", "частично"}
    assert out["rows"]
    keys = {row["key"] for row in out["rows"]}
    assert "RUB" not in keys
    assert "RU" not in keys
    assert "fund" not in keys
    assert "unknown" in keys


def test_broker_view_uses_holding_fields(monkeypatch) -> None:
    monkeypatch.setattr(svc, "is_enabled", lambda _flag: True)
    monkeypatch.setattr(svc, "all_figi", lambda: [])
    monkeypatch.setattr(svc, "resolve_figi", lambda _t: None)
    monkeypatch.setattr(
        svc,
        "_holdings_from_book",
        lambda *_a, **_k: [
            {
                "ticker": "AAPL",
                "currency": "USD",
                "country": "US",
                "sector": "tech",
                "asset_class": "equity",
            }
        ],
    )
    monkeypatch.setattr(svc, "_nav_weights", lambda *_a, **_k: [Decimal("1")])

    out = svc.lookthrough_portfolio("u1", mode="paper", by="currency", view="broker")
    assert {row["key"] for row in out["rows"]} == {"USD"}
