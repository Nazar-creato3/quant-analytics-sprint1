"""Price-history store: ISS parsing, returns, FX, valuation and liquidity wiring."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from app.services.price_history import moex, service, store


@pytest.fixture()
def history_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICE_HISTORY", "1")
    monkeypatch.setenv("PRICE_HISTORY_DIR", str(tmp_path))
    store.clear_cache()
    yield tmp_path
    store.clear_cache()


def _bars(n: int, start: float = 100.0, step: float = 0.01, value: float = 5e8) -> list[list]:
    day = date.today() - timedelta(days=n + 5)
    out, px = [], start
    for i in range(n):
        px *= 1 + (step if i % 2 else -step / 2)
        out.append([(day + timedelta(days=i)).isoformat(), px, value, value / px, px * 1.01, px * 0.99])
    return out


def test_iss_history_pages_and_bond_face_value(monkeypatch) -> None:
    pages = {
        0: {"history": {"columns": ["TRADEDATE", "CLOSE", "LEGALCLOSEPRICE", "VALUE", "VOLUME", "FACEVALUE", "DURATION", "YIELDCLOSE", "HIGH", "LOW"],
                        "data": [["2026-10-21", 95.0, 95.5, 1e7, 1000, 1000, 1500, 14.2, 96, 94]]},
            "history.cursor": {"columns": ["INDEX", "TOTAL", "PAGESIZE"], "data": [[0, 2, 1]]}},
        1: {"history": {"columns": ["TRADEDATE", "CLOSE", "LEGALCLOSEPRICE", "VALUE", "VOLUME", "FACEVALUE", "DURATION", "YIELDCLOSE", "HIGH", "LOW"],
                        "data": [["2026-10-22", 96.0, None, 2e7, 2000, 1000, 1499, 14.1, 97, 95]]},
            "history.cursor": {"columns": ["INDEX", "TOTAL", "PAGESIZE"], "data": [[1, 2, 1]]}},
    }

    async def fake(url, params=None):
        return pages[int((params or {}).get("start") or 0)]

    monkeypatch.setattr(moex, "fetch_moex_iss_json", fake)
    where = {"engine": "stock", "market": "bonds", "board": "TQOB"}
    bars = asyncio.run(moex.history("SU26238RMFS4", where))
    assert [b[0] for b in bars] == ["2026-10-21", "2026-10-22"]
    assert bars[0][1] == pytest.approx(955.0)  # legal close 95.5% of 1000 ₽ face value
    assert bars[1][1] == pytest.approx(960.0)
    assert where["duration_days"] == 1499 and where["yield"] == 14.1


def test_returns_need_enough_history(history_dir) -> None:
    store.write("SBER", {"source": "moex_iss", "market": "shares", "ccy": "RUB", "bars": _bars(30)})
    assert service.returns("SBER") == []
    store.write("SBER", {"source": "moex_iss", "market": "shares", "ccy": "RUB", "bars": _bars(120)})
    r = service.returns("SBER")
    assert len(r) == 119
    assert service.last("SBER")[1] > 0


def test_fx_and_rub_turnover(history_dir) -> None:
    store.write("FX_USD", {"source": "cbr", "market": "fx", "ccy": "RUB", "bars": [["2026-10-23", 80.0, None, None]]})
    store.write("AAPL", {"source": "us_eod", "market": "us", "ccy": "USD", "bars": _bars(40, value=1e6)})
    assert service.fx_rate("USD") == 80.0
    assert service.fx_rate("RUB") == 1.0
    assert service.to_rub(10, "USD") == 800.0
    assert service.turnovers_rub("AAPL")[-1] == pytest.approx(8e7)
    assert service.fx_rate("JPY") is None


def test_store_off_in_tests_by_default(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("PRICE_HISTORY", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("PRICE_HISTORY_DIR", str(tmp_path))
    store.write("SBER", {"bars": _bars(120)})
    assert service.returns("SBER") == []


def test_book_risk_and_liquidity_use_history(history_dir) -> None:
    from app.services.position_liquidity.service import portfolio_liquidity
    from app.services.risk_engine.service import compute_risk_for_user
    from app.services.risk_engine.series import reset
    from app.services.sample_portfolio.service import load_sample

    reset()
    for i, t in enumerate(("SBER", "LKOH", "GAZP", "YDEX", "MOEX", "LQDT", "ROSN", "PLZL")):
        store.write(t, {"source": "moex_iss", "market": "shares", "ccy": "RUB", "bars": _bars(200, start=100 + i * 10, step=0.01 + i / 1000)})
    store.write("SU26238RMFS4", {"source": "moex_iss", "market": "bonds", "ccy": "RUB", "duration_days": 2000, "yield": 14.0, "bars": _bars(200, start=600, step=0.002)})
    load_sample("ph-user")
    risk = compute_risk_for_user("ph-user", "paper")
    assert risk["var_95"] is not None
    assert {c["ticker"] for c in risk["attribution"]["components"]} >= {"SBER", "LKOH"}
    liq = portfolio_liquidity("ph-user", "paper")
    assert liq["share_1d"] is not None and liq["issues"]
    assert liq["data_status"] in {"ok", "частично"}


def test_payouts_from_iss_declared_and_estimated(history_dir) -> None:
    from app.services.payouts.service import cashflow_summary, portfolio_cashflows
    from app.services.sample_portfolio.service import load_sample

    today = date.today()
    last_year = (today - timedelta(days=200)).isoformat()
    declared = (today + timedelta(days=30)).isoformat()
    store.write("PAY_SBER", {"kind": "dividend", "dividends": [{"record_date": last_year, "amount": 33.3, "ccy": "RUB"}]})
    store.write("PAY_LKOH", {"kind": "dividend", "dividends": [{"record_date": declared, "amount": 500.0, "ccy": "RUB"}]})
    store.write("PAY_SU26238RMFS4", {"kind": "bond", "coupons": [
        {"date": (today - timedelta(days=100)).isoformat(), "amount": 35.4},
        {"date": (today + timedelta(days=80)).isoformat(), "amount": 35.4},
        {"date": (today + timedelta(days=260)).isoformat(), "amount": None},
    ], "amortizations": []})
    store.write("SBER", {"market": "shares", "ccy": "RUB", "bars": _bars(100, start=300)})
    load_sample("pay-user")
    out = portfolio_cashflows("pay-user", "paper")
    kinds = {(e["instrument"]["ticker"], e["status"]) for e in out["events"]}
    assert ("LKOH", "declared") in kinds
    assert ("SBER", "estimated") in kinds  # repeats last year, marked
    assert ("SU26238RMFS4", "scheduled") in kinds and ("SU26238RMFS4", "estimated") in kinds
    lkoh = next(e for e in out["events"] if e["instrument"]["ticker"] == "LKOH")
    assert lkoh["amount_gross_rub"] == pytest.approx(500.0 * 12)
    summary = cashflow_summary("pay-user", "paper")
    assert summary["passive_declared_net_12m"] > 0 and summary["estimated_net_12m"] > 0
    assert summary["yields"]["issues"][0]["ticker"] == "SBER"


def test_bond_panel_from_iss(history_dir) -> None:
    from app.services.bonds.service import portfolio_bonds
    from app.services.sample_portfolio.service import load_sample

    today = date.today()
    store.write("SU26238RMFS4", {"market": "bonds", "ccy": "RUB", "facevalue": 1000, "clean_pct": 60.0, "aci": 10.0,
                                  "matdate": "2041-05-15", "bars": _bars(100, start=600, step=0.001)})
    coupons = [{"date": (today + timedelta(days=30 + 182 * i)).isoformat(), "amount": 35.4} for i in range(30)]
    store.write("PAY_SU26238RMFS4", {"kind": "bond", "coupons": coupons, "amortizations": []})
    load_sample("bond-user")
    out = portfolio_bonds("bond-user", "paper")
    row = out["issues"][0]
    assert row["secid"] == "SU26238RMFS4"
    assert row["dirty_price"] == pytest.approx(610.0)
    assert row["ytm"] is not None and 0.05 < row["ytm"] < 0.3
    assert row["duration"] is not None and row["duration"] > 5


def test_screener_ru_rows_from_iss(history_dir, monkeypatch) -> None:
    from app.services.screener import moex_rows
    from app.services.screener.service import filter_rows

    payload = {
        "securities": {"columns": ["SECID", "SHORTNAME", "SECNAME", "PREVPRICE", "ISSUESIZE", "LISTLEVEL"],
                       "data": [["SBER", "Сбербанк", "ПАО Сбербанк", 300.0, 21586948000, 1], ["ZZZZ", "Нечто", "Нечто", 5.0, 1000, 3]]},
        "marketdata": {"columns": ["SECID", "LAST", "MARKETPRICE", "VALTODAY", "VALTODAY_RUR", "VOLTODAY", "ISSUECAPITALIZATION"],
                       "data": [["SBER", 310.0, 309.0, 5e9, 5e9, 1.6e7, 6.7e12], ["ZZZZ", None, None, 0, 0, 0, None]]},
    }

    async def fake(url, params=None):
        return payload

    monkeypatch.setattr(moex_rows, "fetch_moex_iss_json", fake)
    moex_rows._snapshot.update(at=0.0, rows=[])
    store.write("FX_USD", {"market": "fx", "ccy": "RUB", "bars": [["2026-10-23", 80.0, None, None]]})
    store.write("SBER", {"market": "shares", "ccy": "RUB", "bars": _bars(300, start=300)})
    store.write("IMOEX", {"market": "index", "ccy": "RUB", "bars": _bars(300, start=3000)})
    rows = asyncio.run(moex_rows.rows())
    sber = next(r for r in rows if r["symbol"] == "SBER")
    assert sber["price"] == 310.0 and sber["sector"] == "Financial Services"
    assert sber["market_cap"] == pytest.approx(6.7e12 / 80.0)
    assert sber["volatility"] is not None and sber["es_975"] is not None and sber["beta"] is not None
    assert sber["pe"] is None  # no T-Invest token → honest gap, not 0
    zz = next(r for r in rows if r["symbol"] == "ZZZZ")
    assert zz["price"] == 5.0 and zz["market_cap"] == pytest.approx(5000 / 80.0)
    big = filter_rows(rows, {"marketCapMoreThan": 1e10, "limit": 50})
    assert [r["symbol"] for r in big] == ["SBER"]
