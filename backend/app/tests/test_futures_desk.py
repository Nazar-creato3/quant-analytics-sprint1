"""Futures desk: ISS FORTS rows in plain terms, front contract, user futures, hedge inputs."""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from app.services.futures_desk import service as fd

SEC_COLS = ["SECID", "SHORTNAME", "SECNAME", "PREVSETTLEPRICE", "MINSTEP", "STEPPRICE", "LASTTRADEDATE", "ASSETCODE",
            "INITIALMARGIN", "LASTSETTLEPRICE", "LOTVOLUME", "PREVOPENPOSITION", "BUYSELLFEE"]
MD_COLS = ["SECID", "LAST", "SETTLEPRICE", "OPENPOSITION", "VOLTODAY", "VALTODAY", "BID", "OFFER", "UPDATETIME"]


def _payload():
    return {
        "securities": {"columns": SEC_COLS, "data": [
            ["MXZ6", "MIX-12.26", "Фьючерс MIX-12.26", 2800.0, 0.05, 0.5, "2026-12-17", "MIX", 42000.0, 2800.0, 1, 50000, 2.0],
            ["MXH7", "MIX-3.27", "Фьючерс MIX-3.27", 2850.0, 0.05, 0.5, "2027-03-18", "MIX", 43000.0, 2850.0, 1, 3000, 2.0],
            ["SiZ6", "Si-12.26", "Фьючерс Si-12.26", 82000.0, 1.0, 1.0, "2026-12-17", "Si", 12000.0, 82000.0, 1000, 900000, 1.0],
            ["IMOEXF", "IMOEXF", "Вечный IMOEX", 2790.0, 0.5, 5.0, "2099-12-31", "IMOEXF", 40000.0, 2790.0, 1, 200000, 2.0],
            ["MXU6", "MIX-9.26", "истёк", 2700.0, 0.05, 0.5, "2026-09-17", "MIX", 41000.0, 2700.0, 1, 0, 2.0],
        ]},
        "marketdata": {"columns": MD_COLS, "data": [
            ["MXZ6", 2828.0, 2827.0, 51000, 12000, 3.4e10, 2827.5, 2828.5, "18:40:00"],
            ["MXH7", 2870.0, None, 3100, 100, 1e8, None, None, "18:40:00"],
            ["SiZ6", 82500.0, None, 910000, 300000, 2.4e10, None, None, "18:40:00"],
            ["IMOEXF", 2795.0, None, 210000, 50000, 1e10, None, None, "18:40:00"],
        ]},
    }


def test_contract_terms_in_roubles() -> None:
    sec = dict(zip(SEC_COLS, _payload()["securities"]["data"][0]))
    md = dict(zip(MD_COLS, _payload()["marketdata"]["data"][0]))
    row = fd.contract_row(sec, md, today=date(2026, 10, 24))
    assert row["point_value"] == pytest.approx(10.0)  # 0.5 ₽ per 0.05 pt
    assert row["contract_value"] == pytest.approx(28280.0)
    assert row["leverage"] == pytest.approx(28280.0 / 42000.0)
    assert row["days_to_expiry"] == 54 and not row["perpetual"]
    assert row["change"] == pytest.approx(2828 / 2800 - 1)


def test_front_contract_and_perpetual(monkeypatch) -> None:
    async def fake(url, params=None):
        return _payload()

    monkeypatch.setattr(fd, "fetch_moex_iss_json", fake)
    fd._cache.update(at=0.0, rows=[])
    rows = asyncio.run(fd.board(today=date(2026, 10, 24)))
    assert "MXU6" not in {r["secid"] for r in rows}  # expired contract dropped
    keys = {r["asset"]: r for r in fd.key_contracts(rows)}
    assert keys["MIX"]["secid"] == "MXZ6" and keys["MIX"]["next_secid"] == "MXH7"
    assert keys["SI"]["contract_value"] == pytest.approx(82500.0)
    assert keys["IMOEXF"]["perpetual"] and keys["IMOEXF"]["days_to_expiry"] is None
    assert [h["secid"] for h in fd.search(rows, "mix")][:1] == ["MXZ6"]


def test_my_futures_variation_and_roll(monkeypatch) -> None:
    from app.services.portfolio_book.service import ensure_account, record_transaction
    from datetime import datetime, timezone

    async def fake(url, params=None):
        return _payload()

    monkeypatch.setattr(fd, "fetch_moex_iss_json", fake)
    fd._cache.update(at=0.0, rows=[])
    rows = asyncio.run(fd.board(today=date(2026, 12, 12)))
    ensure_account(account_id="fut:u", user_id="fut-u", venue="paper", mode="paper", source="test")
    record_transaction(account_id="fut:u", user_id="fut-u", mode="paper", venue="paper", external_id="fut-1", kind="trade",
                       instrument_id="MXZ6", ticker="MXZ6", qty="-2", amount="-5600", ccy="RUB",
                       event_time=datetime(2026, 11, 1, tzinfo=timezone.utc))
    mine = fd.my_futures("fut-u", "paper", rows)
    assert len(mine) == 1
    p = mine[0]
    assert p["side"] == "short" and p["margin"] == pytest.approx(84000.0)
    assert p["variation_today"] == pytest.approx((2828 - 2800) * 10 * -2)
    assert p["pnl_since_entry"] == pytest.approx((2828 - 2800) * 10 * -2)
    assert p["roll_soon"] is True


def test_freshness_judged_from_data_not_credentials():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.services.futures_desk.service import freshness

    msk = ZoneInfo("Europe/Moscow")
    friday_noon = datetime(2026, 10, 23, 12, 0, tzinfo=msk)
    assert freshness([{"updated": "11:59:30"}], now=friday_noon) == "realtime"
    assert freshness([{"updated": "11:44:00"}], now=friday_noon) == "delayed"
    assert freshness([{"updated": "18:00:00"}], now=datetime(2026, 10, 24, 12, 0, tzinfo=msk)) == "closed"
