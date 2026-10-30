"""GA-058…060: construction refuses missing mandate, price, or vol."""
from __future__ import annotations

import pytest

from app.services.construction.construct import construct_sleeve


def test_ga058_mandate_exception_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("ips down")

    monkeypatch.setattr("app.services.platform_desk.mandate.load_ips", boom)
    book = construct_sleeve(
        [{"symbol": "AAA", "vol": 0.2, "price": 10, "adv_usd": 1e6, "p_beat_21": 0.8}],
        settings_cap=250,
        account_total=250,
        user_id="ga058",
    )
    assert book["holdings"] == []
    assert book["book_usd"] == 0.0
    assert "нет данных" in book["rejected"]
    assert book.get("data_status") == "нет данных"


def test_ga059_missing_price_skips_name() -> None:
    book = construct_sleeve(
        [
            {"symbol": "NOPX", "vol": 0.2, "adv_usd": 1e7, "p_beat_21": 0.9},
            {"symbol": "OK", "vol": 0.2, "price": 10, "atr": 0.3, "adv_usd": 1e7, "p_beat_21": 0.8},
        ],
        settings_cap=250,
        account_total=250,
    )
    held = {h["symbol"] for h in book["holdings"]}
    assert "NOPX" not in held
    assert any(r.startswith("NOPX:") and "нет данных" in r for r in book["rejected"])


def test_ga060_missing_vol_skips_name() -> None:
    book = construct_sleeve(
        [{"symbol": "NVOL", "price": 10, "atr": 0.3, "adv_usd": 1e7, "p_beat_21": 0.9}],
        settings_cap=250,
        account_total=250,
    )
    assert book["holdings"] == []
    assert any("NVOL" in r and "нет данных" in r for r in book["rejected"])
