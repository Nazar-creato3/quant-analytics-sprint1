"""K1 RGBITR + money-market vs book TWR/MWR. Golden 01B to the kopeck."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.benchmark_alt.prices import put_prices, reset as reset_prices
from app.services.benchmark_alt.replay import replay_index_cashflows
from app.services.benchmark_alt.service import as_dict, compare_simple_alternatives
from app.services.portfolio_book.service import ensure_account, record_transaction
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import reset_for_tests, set_global
from app.tests.qa_session import bind_session_user, clear_session_user

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / "docs" / "qa" / "golden" / "k1_simple_alternative.json"
sys.path.insert(0, str(REPO))
from validation.golden.independent import replay_index_cashflows as independent_replay  # noqa: E402


def setup_function() -> None:
    reset_for_tests()
    get_book().reset()
    reset_prices()


def teardown_function() -> None:
    get_book().reset()
    reset_prices()
    reset_for_tests()
    clear_session_user()


def _payload() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _pairs(rows: list[list[str]]) -> list[tuple[date, Decimal]]:
    return [(date.fromisoformat(day), Decimal(price)) for day, price in rows]


def test_k1_ui_texts_keys() -> None:
    from app.services.legal.catalog import load_ui_texts, reset_cache

    reset_cache()
    k1 = load_ui_texts()["k1"]
    assert k1["title"] == "Портфель и простая альтернатива"
    blob = " ".join(str(v).lower() for v in k1.values())
    assert "стоит купить" not in blob
    assert "без риска" not in blob
    assert "плохо" not in blob
    assert "выгодно" not in blob


def test_golden_independent_matches_json() -> None:
    payload = _payload()
    as_of = date.fromisoformat(payload["as_of"])
    flows = _pairs(payload["cashflows"])
    expected = payload["expected"]
    rgbitr = independent_replay(flows, _pairs(payload["prices"]["RGBITR"]), as_of)
    lqdt = independent_replay(flows, _pairs(payload["prices"]["LQDT"]), as_of)
    assert rgbitr["end_value"] == Decimal(expected["rgbitr_end"])
    assert lqdt["end_value"] == Decimal(expected["lqdt_end"])
    assert abs(rgbitr["twr"] - Decimal(expected["rgbitr_twr"])) <= Decimal(expected["tolerance"]["twr"])
    assert abs(lqdt["twr"] - Decimal(expected["lqdt_twr"])) <= Decimal(expected["tolerance"]["twr"])
    assert abs(rgbitr["mwr"] - Decimal(expected["rgbitr_mwr"])) <= Decimal(expected["tolerance"]["mwr"])
    assert abs(lqdt["mwr"] - Decimal(expected["lqdt_mwr"])) <= Decimal(expected["tolerance"]["mwr"])
    port_end = Decimal(payload["portfolio_end"])
    assert (port_end - rgbitr["end_value"]) == Decimal(expected["diff_value_rgbitr"])
    assert (port_end - lqdt["end_value"]) == Decimal(expected["diff_value_lqdt"])


def test_production_replay_matches_independent_to_kopeck() -> None:
    payload = _payload()
    as_of = date.fromisoformat(payload["as_of"])
    flows = _pairs(payload["cashflows"])
    for ticker in ("RGBITR", "LQDT"):
        prod = replay_index_cashflows(flows, _pairs(payload["prices"][ticker]), as_of)
        indie = independent_replay(flows, _pairs(payload["prices"][ticker]), as_of)
        assert prod["end_value"] == indie["end_value"]
        assert abs(prod["twr"] - indie["twr"]) <= Decimal("0.00000001")
        assert abs(prod["mwr"] - indie["mwr"]) <= Decimal("0.0001")


def _seed_book_and_prices(user: str = "k1u") -> None:
    payload = _payload()
    ensure_account(account_id="k1", user_id=user, venue="bots", mode="paper")
    for idx, (day, amount) in enumerate(_pairs(payload["cashflows"])):
        record_transaction(
            account_id="k1",
            user_id=user,
            mode="paper",
            venue="bots",
            external_id=f"k1-d{idx}",
            kind="deposit",
            instrument_id="CASH",
            ticker="CASH",
            qty="0",
            amount=str(amount),
            ccy="RUB",
            event_time=datetime(day.year, day.month, day.day, tzinfo=timezone.utc),
        )
    for ticker, rows in payload["prices"].items():
        put_prices(ticker, _pairs(rows), source="synthetic_golden_k1")


def test_compare_uses_returns_and_golden_alts() -> None:
    payload = _payload()
    _seed_book_and_prices()
    as_of = date.fromisoformat(payload["as_of"])
    out = compare_simple_alternatives(user_id="k1u", mode="paper", today=as_of)
    expected = payload["expected"]
    by_ticker = {row["ticker"]: row for row in out["alternatives"]}
    assert by_ticker["RGBITR"]["end_value"] == Decimal(expected["rgbitr_end"])
    assert by_ticker["LQDT"]["end_value"] == Decimal(expected["lqdt_end"])
    assert out["portfolio"]["end_value"] is not None
    assert by_ticker["RGBITR"]["diff_value"] == (
        Decimal(out["portfolio"]["end_value"]) - Decimal(expected["rgbitr_end"])
    )


def test_withdrawal_replay_matches_independent() -> None:
    as_of = date(2024, 1, 31)
    flows = [
        (date(2024, 1, 1), Decimal("100000.00")),
        (date(2024, 1, 15), Decimal("-20000.00")),
    ]
    prices = [
        (date(2024, 1, 1), Decimal("600")),
        (date(2024, 1, 15), Decimal("603")),
        (date(2024, 1, 31), Decimal("606")),
    ]
    prod = replay_index_cashflows(flows, prices, as_of)
    indie = independent_replay(flows, prices, as_of)
    assert prod["end_value"] == indie["end_value"]
    assert prod["end_value"] == Decimal("80900.50")
    assert abs(prod["twr"] - indie["twr"]) <= Decimal("0.00000001")


def test_missing_price_is_no_data() -> None:
    _seed_book_and_prices()
    reset_prices()
    out = compare_simple_alternatives(user_id="k1u", mode="paper", today=date(2024, 1, 31))
    assert out["data_status"] in {"нет данных", "частично"}
    assert all(row["end_value"] is None for row in out["alternatives"])


def test_api_and_flag() -> None:
    _seed_book_and_prices("k1api")
    bind_session_user("k1api")
    client = TestClient(app)
    body = client.get("/api/v1/returns/simple-alts", params={"mode": "paper", "period": "inception"})
    assert body.status_code == 200
    payload = body.json()
    assert "alternatives" in payload
    assert payload["portfolio"]["twr"] is not None or payload["data_status"]
    serial = as_dict(compare_simple_alternatives(user_id="k1api", mode="paper", today=date(2024, 1, 31)))
    assert serial["alternatives"][0]["end_value"] is None or isinstance(serial["alternatives"][0]["end_value"], str)
    assert serial["alternatives"][0]["source"] == "официальное закрытие"
    assert "synthetic" not in serial["alternatives"][0]["source"]
    assert "equity_eod" not in str(serial["alternatives"])
    set_global("qa_k1_benchmark", False)
    off = client.get("/api/v1/returns/simple-alts")
    assert off.status_code == 404
