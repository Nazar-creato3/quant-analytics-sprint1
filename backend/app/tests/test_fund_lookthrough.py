"""Prompt 61: look-through golden, parsers, undisclosed fund, API."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.fund_lookthrough import router as lookthrough_router
from app.services.fund_lookthrough.expand import expand_fund
from app.services.fund_lookthrough.parsers import UK_NAMES, parse_iss_analytics, parse_uk_csv
from app.services.fund_lookthrough.service import issuer_weights, lookthrough_portfolio
from app.services.fund_lookthrough.store import load_manual_dir, reset, upsert_yaml
from app.services.portfolio_book.service import ensure_account, record_transaction
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import reset_for_tests, set_global
from app.services.qa.session_user import require_session_user_id

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "61"
GOLDEN_SBER = Decimal("0.187")


def setup_function() -> None:
    reset_for_tests()
    set_global("qa_fund_lookthrough", True)
    get_book().reset()
    reset()
    load_manual_dir()


def teardown_function() -> None:
    get_book().reset()
    reset()
    reset_for_tests()


def _seed_golden(user_id: str = "lt61") -> None:
    ensure_account(account_id="a61", user_id=user_id, venue="demo", mode="paper")
    when = datetime(2026, 9, 30, tzinfo=timezone.utc)
    for i, (ticker, qty) in enumerate(
        (("SBER", "10"), ("TMOS", "50"), ("BOND_F", "20"), ("FOF_X", "20")),
        start=1,
    ):
        record_transaction(
            account_id="a61",
            user_id=user_id,
            mode="paper",
            venue="demo",
            external_id=f"t{i}",
            kind="trade",
            instrument_id=ticker,
            ticker=ticker,
            qty=qty,
            amount=str(Decimal(qty) * Decimal("10")),
            ccy="RUB",
            event_time=when,
        )


def test_golden_sber_lookthrough_matches_hand() -> None:
    _seed_golden()
    payload = lookthrough_portfolio("lt61", by="issuer", view="lookthrough")
    sber = next(row for row in payload["rows"] if row["key"] == "SBER")
    assert Decimal(sber["weight"]) == GOLDEN_SBER
    assert payload["data_status"] == "ok"
    by_class = lookthrough_portfolio("lt61", by="asset_class")
    weights = {row["key"]: Decimal(row["weight"]) for row in by_class["rows"]}
    assert weights["equity"] == Decimal("0.70")
    assert weights["bond"] == Decimal("0.30")


def test_hidden_and_overlap() -> None:
    _seed_golden()
    payload = lookthrough_portfolio("lt61", by="issuer")
    hidden = {row["issuer"]: Decimal(row["lookthrough"]) for row in payload["hidden"]}
    assert hidden["SBER"] == GOLDEN_SBER
    pairs = {(row["left"], row["right"]): Decimal(row["overlap"]) for row in payload["overlaps"]}
    assert pairs[("TMOS", "FOF_X")] == Decimal("0.50")
    assert pairs[("BOND_F", "FOF_X")] == Decimal("0.50")
    assert pairs[("TMOS", "BOND_F")] == Decimal("0")


def test_broker_view_keeps_fund_line() -> None:
    _seed_golden()
    broker = lookthrough_portfolio("lt61", by="issuer", view="broker")
    keys = {row["key"]: Decimal(row["weight"]) for row in broker["rows"]}
    assert keys["TMOS"] == Decimal("0.5")
    assert keys["SBER"] == Decimal("0.1")
    assert broker["hidden"] == []


def test_undisclosed_fund_stays_one_line() -> None:
    upsert_yaml(
        {
            "fund_figi": "BBGNONE",
            "ticker": "BLANKF",
            "as_of": "2026-09-30",
            "source": "manual",
            "holdings": [],
        }
    )
    ensure_account(account_id="a62", user_id="u62", venue="demo", mode="paper")
    record_transaction(
        account_id="a62",
        user_id="u62",
        mode="paper",
        venue="demo",
        external_id="b1",
        kind="trade",
        instrument_id="BLANKF",
        ticker="BLANKF",
        qty="1",
        amount="100",
        ccy="RUB",
        event_time=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )
    payload = lookthrough_portfolio("u62", by="issuer")
    assert payload["data_status"] == "частично"
    assert payload["rows"][0]["key"] == "BBGNONE"
    assert payload["rows"][0]["disclosed"] is False
    assert "состав не раскрыт" in (payload["reason"] or "")


def test_no_positions_is_net_dannykh() -> None:
    payload = lookthrough_portfolio("nobody")
    assert payload["data_status"] == "нет данных"
    assert payload["rows"] == []
    assert issuer_weights("nobody") == {}


def test_iss_and_uk_parsers() -> None:
    iss = json.loads((FIXTURES / "iss_imoex.json").read_text(encoding="utf-8"))
    parsed = parse_iss_analytics(
        iss,
        index_code="IMOEX",
        as_of=date(2026, 9, 30),
        source_url="https://iss.moex.com/iss/reference/",
    )
    assert parsed["composition_note"] == "состав по индексу"
    assert parsed["holdings"][0]["weight"] == "0.12"
    for uk in UK_NAMES:
        text = (FIXTURES / "uk" / f"{uk}.csv").read_text(encoding="utf-8")
        doc = parse_uk_csv(uk, text, fund_figi=f"UK:{uk}", as_of=date(2026, 9, 30), source_url="https://example.test")
        assert doc["holdings"]
        assert Decimal(doc["holdings"][0]["weight"]) > 0


def _mini_app() -> FastAPI:
    app = FastAPI()
    app.include_router(lookthrough_router, prefix="/api/v1")
    return app


def test_api_session_and_flag() -> None:
    _seed_golden()
    app = _mini_app()
    app.dependency_overrides[require_session_user_id] = lambda: "lt61"
    client = TestClient(app)
    res = client.get("/api/v1/portfolio/me/lookthrough", params={"by": "issuer"})
    assert res.status_code == 200
    assert res.json()["source"] == "состав фонда"
    assert "manual/index" not in res.json()["source"]
    assert Decimal(next(r["weight"] for r in res.json()["rows"] if r["key"] == "SBER")) == GOLDEN_SBER
    funds = client.get("/api/v1/funds/TMOS/holdings")
    assert funds.status_code == 200
    assert funds.json()["as_of"] == "2026-09-30"
    named = client.get("/api/v1/portfolio/lt61/lookthrough", params={"by": "country"})
    assert named.status_code == 200
    assert Decimal(next(r["weight"] for r in named.json()["rows"] if r["key"] == "RU")) == Decimal("1")
    set_global("qa_fund_lookthrough", False)
    off = client.get("/api/v1/portfolio/me/lookthrough")
    assert off.status_code == 404
    anon = TestClient(_mini_app())
    assert anon.get("/api/v1/portfolio/me/lookthrough").status_code == 401


def test_lookthrough_ui_texts_keys() -> None:
    from app.services.legal.catalog import load_ui_texts, reset_cache

    reset_cache()
    block = load_ui_texts()["lookthrough"]
    for key in (
        "title",
        "view_broker",
        "view_lookthrough",
        "hidden_title",
        "method_intro",
        "method_expand",
        "undisclosed",
    ):
        assert block[key]


def test_country_sector_currency_slices() -> None:
    _seed_golden()
    country = {row["key"]: Decimal(row["weight"]) for row in lookthrough_portfolio("lt61", by="country")["rows"]}
    assert country["RU"] == Decimal("1")
    currency = {row["key"]: Decimal(row["weight"]) for row in lookthrough_portfolio("lt61", by="currency")["rows"]}
    assert currency["RUB"] == Decimal("1")
    sector = {row["key"]: Decimal(row["weight"]) for row in lookthrough_portfolio("lt61", by="sector")["rows"]}
    assert sector["banks"] == Decimal("0.087")


def test_depth_stops_at_three() -> None:
    leaf_eq = {
        "holding_isin": "RU0009029540",
        "holding_name": "SBER",
        "issuer": "SBER",
        "weight": "1",
        "asset_class": "equity",
        "currency": "RUB",
        "country": "RU",
        "sector": "banks",
    }
    upsert_yaml(
        {
            "fund_figi": "L4",
            "ticker": "L4",
            "as_of": "2026-09-30",
            "source": "manual",
            "holdings": [leaf_eq],
        }
    )
    for parent, child in (("L3", "L4"), ("L2", "L3"), ("L1", "L2")):
        upsert_yaml(
            {
                "fund_figi": parent,
                "ticker": parent,
                "as_of": "2026-09-30",
                "source": "manual",
                "holdings": [
                    {
                        "holding_isin": child,
                        "holding_name": child,
                        "issuer": child,
                        "weight": "1",
                        "asset_class": "fund",
                        "currency": "RUB",
                        "country": "RU",
                        "sector": "fund",
                        "is_fund": True,
                        "child_figi": child,
                    }
                ],
            }
        )
    leaves = expand_fund("L1", Decimal("1"))
    keys = {str(row["key"]) for row in leaves}
    assert "L4" in keys
    assert "RU0009029540" not in keys
    assert "SBER" not in keys


def test_stale_composition_flag() -> None:
    upsert_yaml(
        {
            "fund_figi": "OLD1",
            "ticker": "OLD1",
            "as_of": "2026-01-01",
            "source": "manual",
            "holdings": [
                {
                    "holding_isin": "RU0009029540",
                    "holding_name": "SBER",
                    "issuer": "SBER",
                    "weight": "1",
                    "asset_class": "equity",
                    "currency": "RUB",
                    "country": "RU",
                    "sector": "banks",
                }
            ],
        }
    )
    ensure_account(account_id="a63", user_id="u63", venue="demo", mode="paper")
    record_transaction(
        account_id="a63",
        user_id="u63",
        mode="paper",
        venue="demo",
        external_id="o1",
        kind="trade",
        instrument_id="OLD1",
        ticker="OLD1",
        qty="1",
        amount="100",
        ccy="RUB",
        event_time=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )
    payload = lookthrough_portfolio("u63", by="issuer")
    assert payload["stale"] is True
    assert all(row["stale"] for row in payload["rows"])


def test_same_issuer_equity_and_bond_together_and_apart() -> None:
    upsert_yaml(
        {
            "fund_figi": "MIX1",
            "ticker": "MIX1",
            "as_of": "2026-09-30",
            "source": "manual",
            "holdings": [
                {
                    "holding_isin": "EQSBER",
                    "holding_name": "SBER",
                    "issuer": "SBER",
                    "weight": "0.4",
                    "asset_class": "equity",
                    "currency": "RUB",
                    "country": "RU",
                    "sector": "banks",
                },
                {
                    "holding_isin": "BNDSBER",
                    "holding_name": "SBERBOND",
                    "issuer": "SBER",
                    "weight": "0.6",
                    "asset_class": "bond",
                    "currency": "RUB",
                    "country": "RU",
                    "sector": "banks",
                },
            ],
        }
    )
    ensure_account(account_id="a64", user_id="u64", venue="demo", mode="paper")
    record_transaction(
        account_id="a64",
        user_id="u64",
        mode="paper",
        venue="demo",
        external_id="m1",
        kind="trade",
        instrument_id="MIX1",
        ticker="MIX1",
        qty="1",
        amount="100",
        ccy="RUB",
        event_time=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )
    by_issuer = lookthrough_portfolio("u64", by="issuer")
    sber = next(row for row in by_issuer["rows"] if row["key"] == "SBER")
    assert Decimal(sber["weight"]) == Decimal("1")
    by_class = lookthrough_portfolio("u64", by="asset_class")
    classes = {row["key"]: Decimal(row["weight"]) for row in by_class["rows"]}
    assert classes["equity"] == Decimal("0.4")
    assert classes["bond"] == Decimal("0.6")
